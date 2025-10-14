from .migrate_richtext import migrate_richtext_to_blocks
from collective.exportimport.import_content import reset_dates
from logging import getLogger
from plone import api
from plone.cachepurging.interfaces import ICachePurgingSettings
from plone.registry.interfaces import IRegistry
from plone.volto.setuphandlers import remove_behavior
from Products.Five import BrowserView
from zope.annotation.interfaces import IAnnotations
from zope.component import queryUtility

import transaction


logger = getLogger(__name__)

MIGRATE_RICHTEXT_CTS = ["Document", "News Item", "Event"]


class FixAll(BrowserView):

    def __call__(self):
        request = self.request
        if not request.form.get("form.submitted", False):
            return self.index()

        portal = api.portal.get()

        # Volto migration

        # This uses the blocks-conversion-tool to migrate to blocks
        logger.info("Start migrating richtext to blocks...")
        migrate_richtext_to_blocks(context=self.context, request=self.request)
        msg = "Finished migrating richtext to blocks"
        transaction.get().note(msg)
        transaction.commit()

        # Reuse the migration-form from plone.volto to do some more tasks
        view = api.content.get_view("custom_migrate_to_volto", portal, request)
        # Yes, wen want to migrate default pages
        view.migrate_default_pages = True
        view.slate = True
        view.service_url = "http://localhost:5001/html"

        # To avoid errors (related to translated folders) we need to add
        # some behaviors to Folders before we migrate Folders to Document
        portal_types = api.portal.get_tool("portal_types")
        behaviors_to_add = ("behavior1", "behavior2")
        fti_folder = portal_types.get("Folder")
        fti_folder.manage_changeProperties(
            behaviors=fti_folder.behaviors + behaviors_to_add
        )

        logger.info("Start migrating Folders to Documents...")
        view.do_migrate_folders()
        msg = "Finished migrating Folders to Documents!"
        transaction.get().note(msg)
        transaction.commit()

        logger.info("Start migrating Collections to Documents...")
        view.migrate_collections()
        msg = "Finished migrating Collections to Documents!"
        transaction.get().note(msg)
        transaction.commit()

        # We get PostgreSQL Shared Memory errors when we do not commit during
        # the process of resetting dates. So we implemented it ourselves using
        # the catalog instead of ZopeFindAndApply (not compatible with batching).
        logger.info("Starting to reset dates for all the objects...")
        catalog = api.portal.get_tool("portal_catalog")

        for index, brain in enumerate(catalog.getAllBrains()):
            obj = brain.getObject()
            if obj is None:
                logger.info(f"Object at path {brain.getPath()} not found, skipping...")
                continue
            reset_dates(obj, brain.getPath())
            if not index % 500:
                logger.info(f"Reset dates for {index} objects.")
                transaction.commit()

        transaction.commit()
        logger.info("Finished resetting dates for all the objects!")

        # Disallow folders and collections again
        portal_types = api.portal.get_tool("portal_types")
        portal_types["Collection"].global_allow = False
        portal_types["Folder"].global_allow = False

        # Disable richtext behavior again
        for type_ in MIGRATE_RICHTEXT_CTS:
            remove_behavior(type_, "plone.richtext")

        # reenable versioning
        types_with_versioning = IAnnotations(portal).get("types_with_versioning", [])
        for portal_type in types_with_versioning:
            fti = portal_types.get(portal_type)
            new_behaviors = list(fti.behaviors)
            new_behaviors.append("plone.versioning")
            if fti and portal_type:
                fti.manage_changeProperties(behaviors=new_behaviors)
                logger.info(f"Reenable versioning for {portal_type}")
        if "types_with_versioning" in IAnnotations(portal):
            del IAnnotations(portal)["types_with_versioning"]
        logger.info("Finished reenabling versioning")
        transaction.commit()

        # Enable cachepurging
        logger.info("Starting to enable cachepurging...")
        registry = queryUtility(IRegistry)
        settings = registry.forInterface(ICachePurgingSettings, check=False)
        settings.enabled = True
        logger.info("Finished enabling cachepurging...")
        logger.info("Finished fixing all content!")

        return request.response.redirect(portal.absolute_url())
