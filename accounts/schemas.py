from marshmallow import Schema, fields, validate


class RegisterSchema(Schema):
    """Validates user registration payloads."""

    username = fields.Str(
        required=True,
        validate=validate.Length(min=3, max=150),
    )
    email = fields.Email(required=True)
    password = fields.Str(
        required=True,
        validate=validate.Length(min=8, max=128),
        load_only=True,
    )


class CustomerAccountCreateSchema(Schema):
    """Validates payloads for creating a new Zuora Customer Account."""

    name = fields.Str(required=True, validate=validate.Length(min=2, max=255))
    email = fields.Email(required=True)
    currency = fields.Str(
        load_default="USD",
        validate=validate.OneOf(["USD", "EUR", "GBP", "INR"]),
    )