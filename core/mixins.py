class MarshmallowValidationMixin:
    """
    Mixin for DRF Class-Based Views to validate request data using a
    Marshmallow Schema. ValidationError is automatically caught by
    core.exceptions.custom_exception_handler.
    """

    def validate_payload(self, schema_cls, data=None, partial=False):
        payload = data if data is not None else self.request.data
        schema = schema_cls()
        return schema.load(payload, partial=partial)