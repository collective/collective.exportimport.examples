from collective.exportimport.serializer import get_dx_blob_path
from plone.app.textfield.interfaces import IRichTextValue
from plone.formwidget.geolocation.interfaces import IGeolocation
from plone.namedfile.interfaces import INamedBlobImage
from plone.namedfile.interfaces import INamedBlobFile
from plone.restapi.serializer.converters import json_compatible
from plone.restapi.interfaces import IJsonCompatible
from zope.component import adapter
from zope.interface import implementer

import logging


LOG = logging.getLogger("your.package.export.converters")


@adapter(IRichTextValue)
@implementer(IJsonCompatible)
def richtext_converter(value):
    return {
        "converter": "richtext",
        "data": json_compatible(value.raw),
        "content-type": json_compatible(value.mimeType),
        "encoding": json_compatible(value.encoding),
    }


@adapter(INamedBlobImage)
@implementer(IJsonCompatible)
def namedblob_image_converter(value):
    return {
        "filename": json_compatible(value.filename),
        "content-type": json_compatible(value.contentType),
        "size": value.getSize(),
        "blob_path": json_compatible(get_dx_blob_path(value)),
    }


@adapter(INamedBlobFile)
@implementer(IJsonCompatible)
def namedblob_file_converter(value):
    return {
        "filename": value.filename,
        "content-type": value.contentType,
        "size": value.getSize(),
        "blob_path": json_compatible(get_dx_blob_path(value)),
    }


@adapter(IGeolocation)
@implementer(IJsonCompatible)
def geolocation_converter(value):
    return {
        "latitude": json_compatible(value.latitude),
        "longitude": json_compatible(value.longitude),
    }
