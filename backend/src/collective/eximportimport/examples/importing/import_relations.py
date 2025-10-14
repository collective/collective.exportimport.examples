from collective.exportimport.import_other import ImportRelations
from operator import itemgetter
from plone import api
from Products.CMFPlone import relationhelper
from zope.annotation.interfaces import IAnnotations

import logging
import transaction


logger = logging.getLogger(__name__)


def batch(iterable, batch_size=500):
    length = len(iterable)
    for batch_start in range(0, length, batch_size):
        yield iterable[batch_start : min(batch_start + batch_size, length)]


RELATIONSHIP_FIELD_MAPPING = {
    "old_field_name": "new_field_name",
}


class CustomImportRelations(ImportRelations):

    def import_relations(self, data):
        ignore = [
            "translationOf",  # old LinguaPlone
            "isReferencing",  # linkintegrity
            "internal_references",  # obsolete
            "link",  # tab
            "link1",  # extranetfrontpage
            "link2",  # extranetfrontpage
            "link3",  # extranetfrontpage
            "link4",  # extranetfrontpage
            "box3_link",  # shopfrontpage
            "box1_link",  # shopfrontpage
            "box2_link",  # shopfrontpage
            "source",  # remotedisplay
            "internally_links_to",  # DoormatReference
            "relatedItems",  # not used anymore
            "relatesTo",  # not used anymore (old relatedItems)
            "iterate-working-copy",  # not used anymore
            "Working Copy Relation",  # not used anymore (old iterate-working-copy)
        ]
        all_fixed_relations = []
        portal = api.portal.get()

        # Add also preview_image relations stored in annotations
        preview_image_relations = IAnnotations(portal).get(
            "preview_image_relations", []
        )
        data += preview_image_relations

        for rel in data:
            if rel["relationship"] in ignore:
                continue
            rel["from_attribute"] = self.get_from_attribute(rel)

            all_fixed_relations.append(rel)

        all_fixed_relations = sorted(
            all_fixed_relations, key=itemgetter("from_uuid", "from_attribute")
        )
        transaction.commit()

        # now we handle the relations
        relationhelper.purge_relations()
        relationhelper.cleanup_intids()

        batch_size = 500
        start = 0
        for batch_relations in batch(all_fixed_relations, batch_size):
            relationhelper.restore_relations(all_relations=batch_relations)
            msg = f"Restored relations {start} to {start + len(batch_relations)}."
            logger.info(msg)
            transaction.commit()
            start += batch_size

        if "preview_image_relations" in IAnnotations(portal):
            del IAnnotations(portal)["preview_image_relations"]
        transaction.commit()
