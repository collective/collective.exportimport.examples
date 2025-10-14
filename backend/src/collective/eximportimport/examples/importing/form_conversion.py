"""
form_conversion.py

Contains logic that parses EasyForm XML data (fields_model, actions_model) and
builds a Volto schemaForm block plus mailer settings.
"""

from xml.etree import ElementTree

import logging
import uuid


logger = logging.getLogger(__name__)

# XML Namespaces
NS_SCHEMA = "{http://namespaces.plone.org/supermodel/schema}"
NS_EASYFORM = "{http://namespaces.plone.org/supermodel/easyform}"
NS_FORM = "{http://namespaces.plone.org/supermodel/form}"


def parse_form_data(form_data):
    """
    Extract 'fields_model', 'actions_model', etc. from form_data,
    returning a structured dict: {'schema': ..., 'actions': [...], 'form': {...}}.
    """
    fields_model = form_data.get("fields_model", "")
    actions_model = form_data.get("actions_model", "")

    schema = convert_fields_model_to_schema(fields_model)
    actions = convert_actions_model(actions_model)

    form_settings = {
        "submit_label": form_data.get("submitLabel", "Senden"),
        "show_cancel": form_data.get("useCancelButton", False),
        "cancel_label": form_data.get("cancel_label", "Abbrechen"),
        "sender": form_data.get("sender", "noreply@example.com"),
        "sender_name": form_data.get("sender_name", "YOURCOMPANY"),
        "subject": form_data.get("subject", ""),
        "data_wipe": form_data.get("data_wipe", -1),
        "enableFormsAPI": form_data.get("enableFormsAPI", True),
        "send_confirmation": form_data.get("send_confirmation", False),
        "confirmation_recipients": form_data.get("confirmation_recipients", ""),
        "send": bool(form_data.get("recipients", False)),
        "recipients": form_data.get("recipients", ""),
        "mail_header": form_data.get("mail_header", ""),
        "mail_footer": form_data.get("mail_footer", ""),
        "success": form_data.get(
            "thankstitle", "Vielen Dank! Sie haben folgende Daten übermittelt:"
        ),
        "thankyou": form_data.get("thanksdescription", ""),
    }

    return {
        "schema": schema,
        "actions": actions,
        "form": form_settings,
    }


def convert_fields_model_to_schema(fields_model):
    """
    Converts the fields_model XML to a simplified Volto form schema.
    """
    schema = {
        "fieldsets": [
            {
                "id": "default",
                "title": "Default",
                "fields": [],
            }
        ],
        "properties": {},
        "required": [],
    }
    if not fields_model:
        return schema

    try:
        tree = ElementTree.fromstring(fields_model.encode("utf-8"))
    except ElementTree.ParseError as e:
        logger.error(f"Error parsing fields_model XML: {e}")
        return schema

    schema_node = tree.find(f"{NS_SCHEMA}schema")
    if schema_node is None:
        return schema

    default_fieldset = schema["fieldsets"][0]
    properties = {}
    required = []

    for el in schema_node:
        if el.tag == f"{NS_SCHEMA}fieldset":
            fs_label = el.attrib.get("label", "").strip()
            if fs_label:
                pseudo_id = f"fieldset-separator-{uuid.uuid4().hex[:6]}"
                pseudo_field = {
                    "id": pseudo_id,
                    "factory": "static_text",
                    "widget": "static_text",
                    "type": "object",
                    "title": fs_label,
                    "value": fs_label,
                    "required": False,
                }
                default_fieldset["fields"].append(pseudo_id)
                properties[pseudo_id] = pseudo_field

            for field_el in el.findall(f".//{NS_SCHEMA}field"):
                field = convert_field(field_el)
                default_fieldset["fields"].append(field["id"])
                properties[field["id"]] = field
                if field.get("required", True):
                    required.append(field["id"])

        elif el.tag == f"{NS_SCHEMA}field":
            field = convert_field(el)
            default_fieldset["fields"].append(field["id"])
            properties[field["id"]] = field
            if field.get("required", True):
                required.append(field["id"])
        else:
            logger.warning(f"Unexpected tag in schema: {el.tag}")

    schema["properties"] = properties
    schema["required"] = required

    # we need to delete the "required" attribute from the field definition
    # as it is not a valid JSON schema attribute
    for field_id in schema["required"]:
        schema["properties"][field_id].pop("required", None)

    return schema


def convert_field(el):
    """
    Convert a single <field name="..." type="..."> element into
    a Volto form field definition.
    """
    fieldname = el.attrib["name"]
    field_type = el.attrib["type"]
    field = {
        "id": fieldname,
        "title": fieldname,
        "type": "string",
        "required": True,
        "queryParameterName": fieldname,
    }

    for attrname, value in el.attrib.items():
        if attrname == "name":
            field["id"] = value
        elif attrname == "type":
            map_field_type(field, field_type)
        elif attrname == f"{NS_EASYFORM}THidden":
            if value == "True":
                field["factory"] = "hidden"
                field["widget"] = "hidden"
        elif attrname == f"{NS_EASYFORM}serverSide":
            if value == "True":
                field["factory"] = "hidden"
                field["widget"] = "hidden"
        elif attrname == f"{NS_EASYFORM}validators":
            apply_validators(field, value)
        elif attrname == f"{NS_EASYFORM}TValidator":
            apply_validators(field, value)
        elif attrname == f"{NS_EASYFORM}TDefault":
            if value and value.startswith("python:request.get("):
                field["queryParameterName"] = value.split("request.get('")[1].split(
                    "')"
                )[0]
            else:
                if value.startswith("python:"):
                    logger.warning(f"Unsupported default value: {value}")
                elif value.startswith("string:"):
                    field["default"] = value[len("string:") :].strip()
                else:
                    field["default"] = value
        else:
            logger.warning(f"Unsupported field attribute: {attrname}")

    for child in el:
        tag = child.tag
        if tag == f"{NS_SCHEMA}title":
            if child.text:
                field["title"] = child.text
        elif tag == f"{NS_SCHEMA}description":
            if child.text:
                if field.get("factory") == "label_boolean_field":
                    field["default"] = child.text
                    field["description"] = ""
                else:
                    field["description"] = child.text
        elif tag == f"{NS_SCHEMA}required":
            field["required"] = child.text != "False"
        elif tag == f"{NS_SCHEMA}default":
            if child.text:
                field["default"] = child.text
        elif tag == f"{NS_SCHEMA}min":
            field["minimum"] = child.text
        elif tag == f"{NS_SCHEMA}max":
            field["maximum"] = child.text
        elif tag == f"{NS_SCHEMA}min_length":
            if child.text:
                field["minLength"] = int(child.text)
        elif tag == f"{NS_SCHEMA}max_length" and child.text:
            if child.text:
                field["maxLength"] = int(child.text)
        elif tag == f"{NS_SCHEMA}values":
            handle_choice_values(field, child)
        elif tag == f"{NS_SCHEMA}rich_label":
            if field.get("factory") == "static_text":
                field["default"] = {"data": child.text or ""}
        elif tag == f"{NS_SCHEMA}value_type":
            handle_multiple_choice(field, child)
        elif tag == f"{NS_FORM}widget":
            handle_widget(field, child)
        else:
            logger.warning(f"Unsupported field tag: {tag}")

    return field


def map_field_type(field, field_type):
    """
    Map old EasyForm field type to an approximate Volto factory/widget.
    """
    match field_type:
        case (
            "collective.easyform.fields.Label" | "collective.easyform.fields.RichLabel"
        ):
            field["factory"] = "static_text"
            field["widget"] = "static_text"
            field["type"] = "object"
            field["required"] = False
        case (
            "plone.namedfile.field.NamedBlobFile"
            | "plone.namedfile.field.NamedBlobImage"
        ):
            field["factory"] = "File Upload"
            field["type"] = "object"
        case "zope.schema.URI":
            field["factory"] = "hidden"
            field["widget"] = "hidden"
            field["type"] = "string"
        case "zope.schema.Password":
            field["factory"] = "label_text_field"
            field["type"] = "string"
        case "plone.schema.email.Email":
            field["factory"] = "label_email"
            field["widget"] = "email"
            field["type"] = "string"
        case "zope.schema.Bool":
            field["factory"] = "label_boolean_field"
            field["type"] = "boolean"
        case "zope.schema.Choice":
            field["factory"] = "label_choice_field"
            field["type"] = "string"
        case "zope.schema.Set":
            field["factory"] = "checkbox_group"
            field["widget"] = "checkbox_group"
            field["type"] = "array"
        case "zope.schema.Date":
            field["factory"] = "label_date_field"
            field["widget"] = "date"
            field["type"] = "string"
        case "zope.schema.Datetime":
            field["factory"] = "label_datetime_field"
            field["widget"] = "datetime"
            field["type"] = "string"
        case "zope.schema.Text":
            field["factory"] = "textarea"
            field["widget"] = "textarea"
            field["type"] = "string"
        case "zope.schema.TextLine":
            field["factory"] = "label_text_field"
            field["type"] = "string"
        case "zope.schema.Int":
            field["factory"] = "number"
            field["type"] = "number"
        case _:
            field["factory"] = "label_text_field"
            field["type"] = "string"
            logger.warning(
                f"Unsupported field type '{field_type}', using label_text_field"
            )


def apply_validators(field, validator_str):
    """
    If old form used validators like isEmail, isDecimal, etc., we guess new factories.
    """
    if validator_str in ["isEmail", "isValidEmail"]:
        field["factory"] = "label_email"
        field["widget"] = "email"
    elif validator_str == "isInternationalPhoneNumber":
        field["factory"] = "phonenumber"
    elif validator_str == "isDecimal":
        field["factory"] = "number"
        field["type"] = "number"
    elif validator_str == "python:False":
        pass
    elif validator_str == "isChecked":
        field["required"] = True
    elif validator_str.startswith("python: test(value==None, False"):
        field["required"] = True
    else:
        logger.warning(f"Unsupported validator: {validator_str}")


def handle_choice_values(field, values_element):
    """
    Handle <values> for Choice fields.
    """
    choices = []
    for element in values_element.findall(f"{NS_SCHEMA}element"):
        if element.text:
            choices.append([element.text, element.text])
    field["choices"] = choices
    field["values"] = [c[0] for c in choices]
    if "factory" not in field:
        field["factory"] = "label_choice_field"


def handle_multiple_choice(field, value_type_el):
    """
    Handle <value_type> for Set fields (multiple choices).
    """
    values_el = value_type_el.find(f"{NS_SCHEMA}values")
    if values_el is not None:
        choices = []
        for element in values_el.findall(f"{NS_SCHEMA}element"):
            if element.text:
                choices.append([element.text, element.text])
        field["choices"] = choices
        field["values"] = [c[0] for c in choices]


def handle_widget(field, widget_el):
    """
    If a form:widget type is a known custom widget, adapt the field factory if needed.
    """

    if field["factory"] == "hidden":
        logger.warning(f"Unsupported widget for hidden field: {widget_el.get('type')}")
        return

    widget_type = widget_el.get("type", "")
    if widget_type.endswith("RadioFieldWidget"):
        if field.get("choices"):
            field["factory"] = "radio_group"
            field["widget"] = "radio_group"
    elif widget_type.endswith("CollectionSelectFieldWidget"):
        if field.get("choices"):
            field["factory"] = "checkbox_group"
            field["widget"] = "checkbox_group"
            field["type"] = "array"
    elif widget_type.endswith("ChoiceWidgetDispatcher"):
        if field.get("choices"):
            field["factory"] = "checkbox_group"
            field["widget"] = "checkbox_group"
            field["type"] = "array"
    elif widget_type.endswith("plone.app.z3cform.widget.SingleCheckBoxBoolFieldWidget"):
        field["factory"] = "label_boolean_field"
        field["type"] = "boolean"
    elif widget_type.endswith("EmailFieldWidget"):
        field["factory"] = "label_email"
        field["widget"] = "email"
        field["type"] = "string"
    elif widget_type.endswith("DateFieldWidget"):
        field["factory"] = "label_date_field"
        field["widget"] = "date"
        field["type"] = "string"
    else:
        logger.warning(f"Unsupported widget type: {widget_type}")


def convert_actions_model(actions_model):
    """
    Convert the <model> with <field type="collective.easyform.actions.Mailer"> nodes.
    """
    actions = []
    if not actions_model:
        return actions

    try:
        tree = ElementTree.fromstring(actions_model.encode("utf-8"))
    except ElementTree.ParseError as e:
        logger.error(f"Error parsing actions_model XML: {e}")
        return actions

    schema_node = tree.find(f"{NS_SCHEMA}schema")
    if not schema_node:
        return actions

    for action_el in schema_node:
        action_type = action_el.attrib.get("type", "")
        required_el = action_el.find(f"{NS_SCHEMA}required")
        if required_el is not None and required_el.text == "False":
            continue

        action_data = {"type": action_type}
        for child in action_el:
            tag_name = child.tag.replace(NS_SCHEMA, "")
            action_data[tag_name] = child.text
        actions.append(action_data)

    return actions


def build_schema_block(id, schema, form_data, mailer_settings):
    """
    Combine final 'schema' with top-level form_data and
    mailer_settings from build_mailer_settings.
    """
    block = {
        "@type": "schemaForm",
        "schema": schema,
        "submit_label": form_data["submit_label"],
        "show_cancel": form_data["show_cancel"],
        "cancel_label": form_data["cancel_label"],
        "success": form_data["success"],
        "thankyou": form_data["thankyou"],
        "sender": form_data["sender"],
        "sender_name": form_data["sender_name"],
        "subject": form_data["subject"],
        "data_wipe": form_data["data_wipe"],
        "send_confirmation": form_data["send_confirmation"],
        "confirmation_recipients": form_data["confirmation_recipients"],
        "send": form_data["send"],
        "recipients": form_data["recipients"],
        "mail_header": {"data": form_data["mail_header"] or ""},
        "mail_footer": {"data": form_data["mail_footer"] or ""},
        "mail_template": "default",
        "enableFormsAPI": True,
        "dataCollectionId": id,
        "captcha": "recaptcha",
    }

    # Merge mailer_settings if present
    if mailer_settings.get("send"):
        block["send"] = True
        block["recipients"] = mailer_settings.get("recipients", "")

    if mailer_settings.get("send_confirmation"):
        block["send_confirmation"] = True
        block["confirmation_recipients"] = mailer_settings.get(
            "confirmation_recipients", ""
        )

    if mailer_settings.get("bcc"):
        block["bcc"] = mailer_settings["bcc"]

    if mailer_settings.get("sender"):
        block["sender"] = mailer_settings["sender"] or "noreply@example.com"
    else:
        block["sender"] = "noreply@example.com"

    if mailer_settings.get("subject"):
        block["subject"] = mailer_settings["subject"]

    if mailer_settings.get("mail_header"):
        block["mail_header"] = mailer_settings["mail_header"]

    if mailer_settings.get("mail_footer"):
        block["mail_footer"] = mailer_settings["mail_footer"]

    if mailer_settings.get("admin_info"):
        block["admin_info"] = mailer_settings["admin_info"]

    if mailer_settings.get("sender_name"):
        block["sender_name"] = mailer_settings["sender_name"] or "YOURCOMPANY"
    else:
        block["sender_name"] = "YOURCOMPANY"

    return block


def build_mailer_settings(actions):
    """
    Identify the single 'user mailer' (if present) and 0..n 'admin mailers'.

    - The user mailer is recognized by 'to_field' (meaning it sends to the form user).
      We use its subject, mail_header (body_pre), mail_footer (body_post + body_footer),
      etc. as the final form's main mail settings (priority).

    - All admin mailers are merged for recipients. If multiple exist, we combine their
      `recipient_email` addresses in a single string separated by ';', and likewise for
      their `bcc_recipients`. We do not override the user mailer's header/footer with
      admin content.

    - If no user mailer exists, we fallback to the first admin mailer for the final
      subject, mail_header, and mail_footer.

    Returns a single dict with these keys:
      {
        "send": bool,
        "recipients": "admin1@x;admin2@x",
        "bcc": "someone@x;someone2@x",
        "sender": "",
        "subject": "",
        "mail_header": {"data": "..."},
        "mail_footer": {"data": "..."},
        "send_confirmation": bool,
        "confirmation_recipients": "...",
      }
    """
    mailers = [
        act
        for act in actions
        if act.get("type") == "collective.easyform.actions.Mailer"
    ]
    if not mailers:
        # No mailers => no mail is sent
        return {
            "send": False,
            "send_confirmation": False,
            "recipients": "",
            "confirmation_recipients": "",
            "bcc": "",
            "sender": "",
            "subject": "",
            "mail_header": {"data": ""},
            "mail_footer": {"data": ""},
        }

    # Separate user mailer vs admin mailers
    user_mailer = None
    admin_mailers = []

    for mailer in mailers:
        to_field = mailer.get("to_field", "") or ""
        if to_field:
            # This is the user mailer
            if user_mailer is not None:
                logger.warning(
                    "Multiple user mailers found."
                    + "Using the first and skipping the rest."
                )
                continue
            user_mailer = mailer
        else:
            # admin mailer
            admin_mailers.append(mailer)

    mailer_settings = {
        "send": False,
        "send_confirmation": False,
        "recipients": "",
        "confirmation_recipients": "",
        "bcc": "",
        "sender": "",
        "subject": "",
        "mail_header": {"data": ""},
        "mail_footer": {"data": ""},
    }
    # 1) Handle admin mailers:
    #    - Combine all recipient_email into one semicolon string
    #    - Combine all cc and bcc_recipients similarly - we add them all to bcc for now.
    #    - Possibly pick subject, sender, etc. from first admin mailer if no user mailer
    admin_recipients = []
    admin_cc = []
    admin_bccs = []

    for idx, adm in enumerate(admin_mailers):
        r = adm.get("recipient_email", "")
        if r:
            admin_recipients.append(r.strip())
        cc = adm.get("bcc_recipients", "")
        if cc:
            admin_cc.append(cc.strip())
        bc = adm.get("bcc_recipients", "")
        if bc:
            admin_bccs.append(bc.strip())

    admin_recipients_str = ";".join(admin_recipients) if admin_recipients else ""
    admin_bccs_str = ";".join(admin_bccs) if admin_bccs else ""
    admin_bccs_str += ";" + ";".join(admin_cc) if admin_cc else ""

    # We'll pick the first admin mailer (if any) for fallback
    # subject/header/footer if user mailer is missing
    first_admin_mailer = admin_mailers[0] if admin_mailers else None

    # 2) Handle user mailer vs. fallback
    if user_mailer:
        # We have a user mailer
        mailer_settings["send_confirmation"] = True
        # The user mailer must have 'to_field';
        # we place it in confirmation_recipients as ${fieldname}
        t_field = user_mailer.get("to_field", "")
        if t_field:
            mailer_settings["confirmation_recipients"] = "${" + t_field + "}"

        # Priority: Use user mailer subject, sender, header, footer
        mailer_settings["subject"] = choose_subject(user_mailer)

        # If there's a senderOverride
        s_override = user_mailer.get("senderOverride", "")
        if s_override:
            mailer_settings["sender"] = parse_sender_override(s_override)

        body_pre = user_mailer.get("body_pre", "") or ""
        body_post = user_mailer.get("body_post", "") or ""
        body_footer = user_mailer.get("body_footer", "") or ""

        # Combine user mailer footers
        combined_footer = body_post
        if body_footer:
            combined_footer += "\n" + body_footer

        mailer_settings["mail_header"] = {"data": body_pre}
        mailer_settings["mail_footer"] = {"data": combined_footer.strip()}

        # For the admin mailers, we'll store them in
        # mailer_settings["recipients"] + mailer_settings["bcc"]
        # If there's at least one admin mailer with a recipient => "send" is True
        if admin_recipients_str:
            mailer_settings["send"] = True
            mailer_settings["recipients"] = admin_recipients_str
        if admin_bccs_str:
            mailer_settings["bcc"] = admin_bccs_str

    else:
        # No user mailer found => fallback to admin mailers only
        # We'll set 'send' to True if there's at least one admin recipient
        if admin_recipients_str:
            mailer_settings["send"] = True
            mailer_settings["recipients"] = admin_recipients_str

        if admin_bccs_str:
            mailer_settings["bcc"] = admin_bccs_str

        # If we have at least one admin mailer, we can fill
        # subject, header, footer from the first
        if first_admin_mailer:
            mailer_settings["subject"] = choose_subject(first_admin_mailer)
            s_override = first_admin_mailer.get("senderOverride", "")

            if s_override:
                mailer_settings["sender"] = parse_sender_override(s_override)

            body_pre = first_admin_mailer.get("body_pre", "") or ""
            body_post = first_admin_mailer.get("body_post", "") or ""
            body_footer = first_admin_mailer.get("body_footer", "") or ""

            combined_footer = body_post
            if body_footer:
                combined_footer += "\n" + body_footer

            mailer_settings["mail_header"] = {"data": body_pre}
            mailer_settings["mail_footer"] = {"data": combined_footer.strip()}

    # Now we merge the possible remaining admin mailer texts into the admin_info
    admin_info_str = ""

    for idx, adm in enumerate(admin_mailers):
        if idx == 0:
            continue
        body_pre = adm.get("body_pre", "") or ""
        body_post = adm.get("body_post", "") or ""
        body_footer = adm.get("body_footer", "") or ""

        combined_footer = body_post
        if body_footer:
            combined_footer += "\n" + body_footer

        admin_info_str += body_pre + "\n" + combined_footer.strip() + "\n"

    if admin_info_str:
        mailer_settings["admin_info"] = admin_info_str

    if mailer_settings.get("sender", ""):
        mailer_settings["sender"] = "noreply@example.com"

    if mailer_settings.get("sender_name", ""):
        mailer_settings["sender_name"] = "YOURCOMPANY"

    return mailer_settings


def choose_subject(mailer):
    """
    If msg_subject or subject_field is set,
    build an appropriate string (like 'Hello' or '${myfield}').
    """
    if mailer.get("msg_subject"):
        return mailer["msg_subject"]
    if mailer.get("subject_field"):
        return f"${{{mailer['subject_field']}}}"
    return ""


def parse_sender_override(override):
    """
    If override is 'string:...' we strip the prefix.
    If it's python or unknown, we return as-is or empty.
    """
    if override.startswith("string:"):
        return override[len("string:") :].strip()
    elif override.startswith("python:"):
        logger.warning(
            f"Unsupported sender override: {override}, use 'noreply@example.com' instead"
        )
        return "noreply@example.com"
    else:
        return override
