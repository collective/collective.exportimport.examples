from plone import api
from plone.protect.interfaces import IDisableCSRFProtection
from Products.Five import BrowserView
from zope.interface import alsoProvides

import logging


LOG = logging.getLogger("your.package.export.export_all")


class ExportAll(BrowserView):

    def __call__(self):
        export_content = api.content.get_view(
            "export_content", self.context, self.request
        )

        # call the view to preload some instance variables in order to
        # call portal_types() afterwards.
        export_content()

        self.request.form["form.submitted"] = True

        # Pin the export settings
        export_content(
            include_blobs=2,  # Export files and images as blob paths
            download_to_server=True,
            migration=True,
            write_errors=True,
            portal_type=[ptype.get("value") for ptype in export_content.portal_types()],
        )

        # remove exports you are 100% sure you don't need for the migration.
        other_exports = [
            "export_relations",
            "export_members",
            "export_translations",
            "export_localroles",
            "export_ordering",
            "export_defaultpages",
            "export_discussion",
            "export_portlets",
            "export_redirects",
        ]

        # disable CSRF protection
        alsoProvides(self.request, IDisableCSRFProtection)

        for name in other_exports:
            view = api.content.get_view(name, self.context, self.request)
            # This saves each export in var/instance/export_xxx.json
            view(download_to_server=True)

        # Important! Redirect to prevent infinite export loop :)
        return self.request.response.redirect(self.context.absolute_url())
