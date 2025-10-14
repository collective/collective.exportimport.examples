from bs4 import BeautifulSoup
from collections import OrderedDict
from collective.exportimport.export_content import ExportContent
from plone.app.blocks.layoutbehavior import ILayoutBehaviorAdaptable
from plone.restapi.serializer.converters import json_compatible
from string import punctuation
from zope.annotation.interfaces import IAnnotations
from zope.component import queryMultiAdapter
from urllib.parse import urlparse, parse_qs

import logging
import re


LOG = logging.getLogger("your.package.export.export_content")


class CustomExportContent(ExportContent):

    known_old_tiles = (
        "your.old.tilename",
    )  # Paste here tiles which are not used anymore in the old system.

    def global_dict_hook(self, item, obj):
        """Use this to modify or skip the serialized data.
        Return None if you want to skip this particular object.
        """
        item = self.handle_tiles(item, obj)
        return item

    def handle_tiles(self, item, obj):
        if obj.getLayout() != "layout_view":
            return item
        if not ILayoutBehaviorAdaptable.providedBy(obj):
            return item

        annotations = IAnnotations(obj)
        tiles = {}
        for key, value in annotations.items():
            if not key.startswith("plone.tiles.data"):
                continue
            tile = json_compatible(value)
            tile.pop("_plone.sacles", None)
            tiles[key] = tile
        if tiles:
            item["_tile_annotations"] = tiles

        if not item.get("customContentLayout"):
            # we don't have any tiles so we can return the item
            return item

        soup = BeautifulSoup(item["customContentLayout"], "html.parser")
        tiles_ref_els = soup.find_all("div", attrs={"data-tile": re.compile(".*")})

        tile_data = OrderedDict()
        path = "/".join(obj.getPhysicalPath())
        for tile_ref_el in tiles_ref_els:
            tile_ref = tile_ref_el["data-tile"]
            if tile_ref.startswith("./@@plone.app.standardtiles.field"):
                continue
            if tile_ref.startswith("./@@plone.app.standardtiles.html?content="):
                tile_path, tile_content = tile_ref.split("content=")
                tile_type_id = tile_path.replace("./@@", "").replace("/", "__")
                tile_data[f"{tile_type_id}"] = json_compatible(tile_content)
                continue
            if tile_ref.startswith("undefined"):
                LOG.warning(f"Tile reference on {path} is undefined: {tile_ref}")
                continue

            try:
                tile_name, tile_id, query = parse_tile_url(tile_ref)
            except ValueError as e:
                LOG.error(f"Error on exporting tile {tile_ref} on {path}: {e}")
                continue

            if tile_name in self.known_old_tiles:
                LOG.info(
                    f"Skip exporting tile {tile_name} on {path} because it is in "
                    "known_old_tiles."
                )
                continue

            tile_view = queryMultiAdapter((obj, self.request), name=tile_name)
            if not tile_view:

                if query and tile_name in [
                    "plone.app.standardtiles.rawembed",
                    "plone.app.standardtiles.image",
                    "plone.app.standardtiles.existingcontent",
                ]:
                    parsed_query = parse_qs(query)
                    data = {k.split(":")[0]: v[0] for k, v in parsed_query.items()}
                    tile_data[f"{tile_name}__{tile_id}"] = json_compatible(data)
                    continue

                LOG.error(f"Cannot get data from tile {tile_ref} on {path}")
                continue

            tile = tile_view[tile_id]

            data = tile.data
            tile_data[f"{tile_name}__{tile_id}"] = json_compatible(data)

        item["_tile_data"] = list(
            tile_data.items()
        )  # convert list of tuples to preserve the order
        return item


def parse_tile_url(tile_url: str):
    parsed_url = urlparse(tile_url)
    query = parsed_url.query
    path_striped = parsed_url.path.strip(punctuation)
    splitted = path_striped.split("/")
    if len(splitted) != 2:
        raise ValueError(f"Invalid tile reference: {tile_url}")
    return tuple(splitted) + (query,)
