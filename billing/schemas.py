from marshmallow import Schema, fields, validate


class SubscriptionCreateSchema(Schema):
    """Validates new subscription creation requests."""

    account_id = fields.UUID(required=True)
    rate_plan_id = fields.UUID(required=True)
    term_start_date = fields.Date(required=True)
    term_end_date = fields.Date(required=True)
    auto_renew = fields.Boolean(load_default=True)


class SubscriptionAmendmentSchema(Schema):
    """Validates mid-term subscription amendments (upgrade, renewal, cancellation)."""

    amendment_type = fields.Str(
        required=True,
        validate=validate.OneOf(["UpdateProduct", "Renewal", "Cancellation"]),
    )
    effective_date = fields.Date(required=True)
    new_rate_plan_id = fields.UUID(load_default=None)
    notes = fields.Str(load_default="", validate=validate.Length(max=500))
    
class PaymentCreateSchema(Schema):
    """Validates payment requests against a specific invoice."""

    invoice_id = fields.UUID(required=True)
    amount = fields.Decimal(
        required=True,
        places=2,
        as_string=False,
        validate=validate.Range(min=0.01),
    )
    payment_method = fields.Str(
        load_default="CreditCard",
        validate=validate.OneOf(["CreditCard", "ACH", "WireTransfer"]),
    )


class RefundCreateSchema(Schema):
    """Validates refund requests against a processed payment."""

    payment_id = fields.UUID(required=True)
    amount = fields.Decimal(
        required=True,
        places=2,
        as_string=False,
        validate=validate.Range(min=0.01),
    )
    reason = fields.Str(required=True, validate=validate.Length(min=3, max=255))