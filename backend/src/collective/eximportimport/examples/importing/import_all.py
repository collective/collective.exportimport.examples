from App.config import getConfiguration
from logging import getLogger
from pathlib import Path
from plone import api
from plone.cachepurging.interfaces import ICachePurgingSettings
from plone.registry.interfaces import IRegistry
from plone.volto.setuphandlers import add_behavior
from Products.Five import BrowserView
from zope.component import queryUtility

import transaction


logger = getLogger(__name__)

DEFAULT_ADDONS = []

MIGRATE_RICHTEXT_CTS = ["Document", "News Item", "Event"]

# Before starting any import/upgrade make sure you have set these
# to environment variable before starting the backend and you have
# started the blocks conversion tool on localhost:5001
# export COLLECTIVE_EXPORTIMPORT_BLOB_HOME= /your/absolute_path/to/blobstore
# Place your export-files in
# /your/absolute_path/migration-example-project/backend/instance/var/import


class ImportAll(BrowserView):

    def __call__(self):
        request = self.request
        if not request.form.get("form.submitted", False):
            return self.index()

        portal = api.portal.get()

        # Fake the target being a classic site even though plone.volto is installed...
        # Allow Folders and Collections (they are disabled in Volto by default)
        portal_types = api.portal.get_tool("portal_types")
        portal_types["Collection"].global_allow = True
        portal_types["Folder"].global_allow = True

        # Enable richtext behavior (otherwise no text will be imported)
        for type_ in MIGRATE_RICHTEXT_CTS:
            add_behavior(type_, "plone.richtext")

        # disable cachepurging
        registry = queryUtility(IRegistry)
        settings = registry.forInterface(ICachePurgingSettings, check=False)
        settings.enabled = False

        transaction.commit()
        cfg = getConfiguration()
        directory = Path(cfg.clienthome) / "import"

        view = api.content.get_view("custom_import_content", portal, request)
        request.form["form.submitted"] = True
        request.form["commit"] = 500
        view(server_file="Plone.json", return_json=True)
        transaction.commit()

        other_imports = [
            ("custom_import_relations", "export_relations.json"),
            # ("import_translations", "export_translations.json"),
            # ("import_localroles", "export_localroles.json"),
            # ("import_ordering", "export_ordering.json"),
            # ("import_defaultpages", "export_defaultpages.json"),
        ]

        for view_name, filename in other_imports:
            view = api.content.get_view(view_name, portal, request)
            path = Path(directory) / filename
            if path.exists():
                results = view(jsonfile=path.read_text(), return_json=True)
                logger.info(results)
                transaction.commit()
            else:
                logger.info(f"Missing file: {path}")

        logger.info("Start updating linkintegrity information...")
        view = api.content.get_view("updateLinkIntegrityInformation", portal, request)
        results = view.update()
        msg = f"Updated linkintegrity for {results} items"
        logger.info(msg)
        transaction.get().note(msg)
        transaction.commit()

        # Rebuilding the catalog is necessary to prevent issues later on
        catalog = api.portal.get_tool("portal_catalog")
        logger.info("Rebuilding catalog...")
        catalog.clearFindAndRebuild()
        msg = "Finished rebuilding catalog!"
        logger.info(msg)
        transaction.get().note(msg)
        transaction.commit()

        logger.info("Finished importing all content!")
