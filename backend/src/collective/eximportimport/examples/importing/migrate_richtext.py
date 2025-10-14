from collective.eximportimport.examples.importing.form_conversion import (
    build_mailer_settings,
)
from collective.eximportimport.examples.importing.form_conversion import (
    build_schema_block,
)
from collective.eximportimport.examples.importing.form_conversion import (
    parse_form_data,
)
from collective.eximportimport.examples.importing.import_content import (
    fix_collection_query,
)
from collective.eximportimport.examples.importing.import_content import (
    get_defered_import_data,
)
from logging import getLogger
from plone import api
from plone.app.uuid.utils import uuidToObject
from uuid import uuid4

import requests
import transaction


logger = getLogger(__name__)


# Copied from plone.volto:browser.migrate_richtext.py
# changed to skip title and description creation on certain content types:


def transform_given_urls(url, internal_as_resolveuid=False, allow_external=False):
    new_link = None
    portal_type = None
    title = None

    if url:
        if "/resolveuid/" in url:
            uuid_from_url = url.split("/resolveuid/")[1]
            uuid = uuid_from_url.replace(
                "/", ""
            )  # Just in case there is a trailing slash
            linked_obj = uuidToObject(uuid)
            if linked_obj is not None:
                if internal_as_resolveuid:
                    new_link = f"/resolveuid/{linked_obj.UID()}"
                    portal_type = linked_obj.portal_type
                    title = linked_obj.title
                else:
                    new_link = "/".join(linked_obj.getPhysicalPath())
                    portal_type = linked_obj.portal_type
                    title = linked_obj.title
            else:
                logger.warning(f"Could not resolve uuid: {uuid} within url: {url}")
        elif url.startswith("http") and allow_external:
            new_link = url
            title = url.replace("https://", "").replace("http://", "")
    return new_link, portal_type, title


def convert_plone_app_standardtiles_html(tile_data, obj, context, requests):
    uuids = []
    blocks = {}

    if (
        tile_data.get("tile_title")
        and len(tile_data.get("tile_title").strip()) > 0
        and tile_data.get("show_title")
    ):
        uuid = str(uuid4())
        blocks[uuid] = create_heading_block(tile_data.get("tile_title"))
        uuids.append(uuid)

    text_blocks, text_uuids = get_blocks_from_richtext(
        tile_data.get("content", tile_data.get("html_snippet", "")),
        service_url="http://localhost:5001/html",
        slate=True,
    )

    blocks.update(text_blocks)
    uuids += text_uuids

    return blocks, uuids


def convert_listing(
    tile_data,
    variation="list",
    showTeaserImage=True,
    showTeaserText=True,
    showTeaserHeading=True,
    showExtendedInfo=False,
    buttonLink=None,
    buttonText="",
):
    if not buttonLink:
        buttonLink = []
    block_item = {
        "@type": "listing",
        "variation": variation,
        "headlineTag": "h2",  # previously this tile had h2 titles
        "showTeaserImage": showTeaserImage,
        "showTeaserText": showTeaserText,
        "showTeaserHeading": showTeaserHeading,
        "showExtendedInfo": showExtendedInfo,
        "buttonText": buttonText,
        "buttonLink": buttonLink,
        "querystring": {},
    }
    query = tile_data.get("query")
    new_query = fix_collection_query(query)
    if new_query:
        block_item["querystring"]["query"] = new_query

    block_item["querystring"]["sort_order_boolean"] = tile_data.get(
        "sort_reversed", False
    )
    if block_item["querystring"]["sort_order_boolean"] is True:
        block_item["sort_order"] = "descending"
        block_item["querystring"]["sort_order"] = "descending"
    elif block_item["querystring"]["sort_order_boolean"] is False:
        block_item["sort_order"] = "ascending"
        block_item["querystring"]["sort_order"] = "ascending"

    limit = tile_data.get("limit")
    if limit:
        block_item["querystring"]["limit"] = str(limit)

    sort_on = tile_data.get("sort_on")
    if sort_on:
        block_item["querystring"]["sort_on"] = sort_on

    uuids = []
    blocks = {}

    title = tile_data.get("title")
    if title and len(title.strip()) > 0:
        uuid = str(uuid4())
        blocks[uuid] = create_heading_block(title)
        uuids.append(uuid)

    description = tile_data.get("description")
    if description and len(description.strip()) > 0:
        uuid = str(uuid4())
        blocks[uuid] = create_slate_block(description)
        uuids.append(uuid)

    uuid = str(uuid4())
    blocks[uuid] = block_item
    uuids.append(uuid)

    return blocks, uuids


def convert_link_list(tile_data, obj, context, requests):
    visible_fields = tile_data.get("visible_fields")
    additional_visible_fields = tile_data.get("additional_visible_fields", [])

    prefilled_data = {
        "variation": "list",  # Other values: "oneThird", "oneQuarter"
        "showTeaserImage": "img" in visible_fields if visible_fields else True,
        "showTeaserText": "entryText" in visible_fields if visible_fields else True,
        "showTeaserHeading": (
            "dateline" in additional_visible_fields
            if additional_visible_fields
            else False
        ),
        "buttonLink": [],  # previously this tile did not allow any button link
        "buttonText": "",  # previously this tile did not allow any button text
    }
    return convert_listing(tile_data, **prefilled_data)


TILE_CONVERTERS = {
    "plone.app.standardtiles.html": convert_plone_app_standardtiles_html,
    "my.custom.list.tile": convert_link_list,
}


def migrate_richtext_to_blocks(
    portal_types=None,
    service_url="http://localhost:5001/html",
    fieldname="text",
    purge_richtext=True,
    slate=True,
    context=None,
    request=None,
):
    blockcount = 0
    pagescount = 0

    if portal_types is None:
        portal_types = types_with_blocks()
    elif isinstance(portal_types, str):
        portal_types = [portal_types]
    results = 0
    for portal_type in portal_types:
        for index, brain in enumerate(
            api.content.find(portal_type=portal_type, sort_on="path"), start=1
        ):
            obj = brain.getObject()
            # text = getattr(obj.aq_base, fieldname, None)

            blocks = {}
            blocks_layout = {"items": []}

            defered_data = get_defered_import_data(obj)

            if obj.portal_type == "Document" and defered_data.get("_form_data"):

                form_blocks, form_uuids = convert_easyform_to_volto_form(
                    defered_data["_form_data"], obj, context, request
                )
                blocks.update(form_blocks)
                blocks_layout["items"] += form_uuids
            else:
                # add description block
                if obj.description:
                    uuid = str(uuid4())
                    blocks[uuid] = {
                        "@type": "description",
                        "fixed": True,
                        "required": True,
                    }
                    blocks_layout["items"].append(uuid)

                for tile in defered_data.get("_tile_data", []):
                    tile_type = tile[0].split("__")[0]
                    tile_data = tile[1]
                    if tile_type in TILE_CONVERTERS:
                        converter = TILE_CONVERTERS[tile_type]
                        result = converter(tile_data, obj, context, request)
                        if isinstance(result, tuple) and len(result) == 2:
                            # The converter returned multiple blocks
                            new_blocks, new_uuids = result
                            blocks.update(new_blocks)
                            blocks_layout["items"] += new_uuids
                        elif isinstance(result, dict):
                            # The converter returned a single block
                            uuid = str(uuid4())
                            blocks[uuid] = result
                            blocks_layout["items"].append(uuid)
                        else:
                            logger.warning(
                                f"Unexpected result {tile_type} on {obj.absolute_url()}"
                            )
                    else:
                        # Flag everything in content so editors clearly see something is
                        # wrong
                        logger.warning(
                            f"Missing Tile: {tile_type} on {obj.absolute_url()}"
                        )
                        uuid = str(uuid4())
                        blocks[uuid] = {
                            "@type": "heading",
                            "heading": f"Missing block: {tile_type}",
                            "tag": "h2",
                        }
                        blocks_layout["items"].append(uuid)

            obj.blocks = blocks
            obj.blocks_layout = blocks_layout
            obj._p_changed = True

            blockcount += len(blocks)
            pagescount += 1

            if purge_richtext:
                setattr(obj, fieldname, None)

            obj.reindexObject(idxs=["SearchableText"])
            results += 1
            logger.debug(f"Migrated richtext to blocks for: {obj.absolute_url()}")

            if not index % 50:  # every 50 items to avoid memory issues
                logger.info(f"Committing after {index} items...")
                transaction.commit()

        msg = f"Migrated {index} {portal_type} to blocks"
        logger.info(msg)

    logger.debug(f"Total pages processed: {pagescount}")
    logger.debug(f"Total blocks created: {blockcount}")

    return results


def create_slate_block(text):
    block = {"@type": "slate", "value": [{"type": "p", "children": [{"text": text}]}]}
    return block


def create_heading_block(text):
    block = {"@type": "heading", "heading": text, "tag": "h2"}
    return block


def get_blocks_from_richtext(
    text,
    service_url="http://localhost:5001/html",
    slate=True,
):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {"html": text}
    if not slate:
        payload["converter"] = "draftjs"
    r = requests.post(service_url, headers=headers, json=payload)
    r.raise_for_status()
    slate_data = r.json()
    slate_data = slate_data["data"]
    blocks = {}
    uuids = []
    # generate slate blocks
    for block in slate_data:
        uuid = str(uuid4())
        uuids.append(uuid)
        blocks[uuid] = block
    return blocks, uuids


def types_with_blocks():
    """A list of content types with volto.blocks behavior."""
    portal_types = api.portal.get_tool("portal_types")
    results = []
    for fti in portal_types.listTypeInfo():
        behaviors = getattr(fti, "behaviors", [])
        if "volto.blocks" in behaviors:
            results.append(fti.id)
    return results


def convert_easyform_to_volto_form(form_data, obj, context, request):
    """
    Given the raw easyForm data (fields_model, actions_model, etc.),
    builds a Volto schemaForm block plus optional prologue & epilogue.
    """
    if not form_data:
        return {}, []

    blocks = {}
    uuids = []

    # Title Block (Fixed)
    title_uuid = str(uuid4())
    blocks[title_uuid] = {
        "@type": "title",
        "fixed": True,
        "required": True,
    }
    uuids.append(title_uuid)

    # Description block, optional and not the usual "description" field
    description = obj.description
    if description:
        description_blocks, description_uuids = get_blocks_from_richtext(
            description, slate=True
        )
        blocks.update(description_blocks)
        uuids += description_uuids

    prologue = form_data.get("formPrologue")
    if prologue:
        prologue_html = prologue.get("data", "")
        if prologue_html:
            prologue_blocks, prologue_uuids = get_blocks_from_richtext(
                prologue_html, slate=True
            )
            blocks.update(prologue_blocks)
            uuids += prologue_uuids

    # Parse the form data
    parsed_data = parse_form_data(form_data)

    # Mailer settings
    mailer_settings = build_mailer_settings(parsed_data.get("actions", []))

    # Build the main schemaForm block
    schema_block = build_schema_block(
        id=obj.id,
        schema=parsed_data["schema"],
        form_data=parsed_data["form"],
        mailer_settings=mailer_settings,
    )

    form_uuid = str(uuid4())
    blocks[form_uuid] = schema_block
    uuids.append(form_uuid)

    epilog = form_data.get("formEpilogue")
    if epilog:
        epilog_html = epilog.get("data", "")
        if epilog_html:
            epilogue_blocks, epilogue_uuids = get_blocks_from_richtext(
                epilog_html, slate=True
            )
            blocks.update(epilogue_blocks)
            uuids += epilogue_uuids

    # thanksPrologue and thanksEpilogue
    thanksProlog = ""
    thanksEpilog = ""
    thanksDescription = ""

    if "thanksDescription" in form_data and form_data["thanksdescription"]:
        thanksDescription = form_data["thanksdescription"] or ""

    if "thanksPrologue" in form_data and form_data["thanksPrologue"]:
        thanksProlog = form_data["thanksPrologue"]["data"] or ""

    if "thanksEpilogue" in form_data and form_data["thanksEpilogue"]:
        thanksEpilog = form_data["thanksEpilogue"]["data"] or ""

    thankyou_message = ""
    if thanksDescription:
        thankyou_message += thanksDescription + "\n"
    if thanksProlog:
        thankyou_message += thanksProlog + "\n"
    thankyou_message += "${formfields}\n"
    if thanksEpilog:
        thankyou_message += thanksEpilog

    schema_block["thankyou"] = thankyou_message

    return blocks, uuids
