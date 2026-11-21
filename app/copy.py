"""Words the app shows when the meaning matters.

The product records rent. It does not collect rent, hold money,
or file tax. If you change a sentence here, keep that promise.
"""

APP_NAME = "Nyumba Book"
TAGLINE = "Record rent. Tenants pay you directly."

# Public sample login. This is not a secret. Do not reuse it for real tenants.
SAMPLE_EMAIL = "demo@nyumbabook.sample"
SAMPLE_PASSWORD = "sample-ledger"

COLLECT_NOTE = (
    "Tenants pay the landlord directly, by cash, MTN MoMo, Airtel Money, or bank. "
    "Nyumba Book only records what you received. It never collects or holds rent."
)

DATE_NOTE = (
    "Rent due follows the month on the schedule. "
    "Recorded money follows the date the tenant paid you. "
    "A payment today for an older month counts in this month's recorded total "
    "and reduces that older month's balance."
)

RECEIPT_DISCLAIMER = (
    "This is a payment record of money the landlord received directly from the tenant. "
    "It is not a ZRA Smart Invoice, not a tax invoice, and not proof that tax was paid. "
    "Nyumba Book does not collect or hold rent."
)

TAX_DISCLAIMER = (
    "Estimate only. This is not tax advice, not a ZRA return, and not a Smart Invoice. "
    "Nyumba Book does not file tax and does not collect rent. "
    "The bands used here are the rental income rates published for 1 January 2026: "
    "0% up to K30,000 a year, 4% on the part from K30,000 to K800,000, and 16% above K800,000. "
    "Tax is estimated on rent you recorded as received (gross turnover), not on profit after repairs or other costs. "
    "Confirm the current bands with the Zambia Revenue Authority and file the monthly return by the 14th."
)

OLD_YEAR_WARNING = (
    "These bands apply from 1 January 2026. Earlier years used a different tax-free amount. "
    "Do not use this estimate for a year before 2026."
)

NIL_BAND_NOTE = (
    "Recorded rent for this year is still inside the first band, so the tax estimate is zero. "
    "A zero estimate does not always mean you can skip registering or filing. Check with ZRA."
)

SAMPLE_BANNER = (
    "Sample data: this boarding house and these tenants are fictional. "
    "Register your own account before you record real rent. "
    "The sample password is public."
)

ZRA_URL = "https://www.zra.org.zm/"

INCOME_CSV_NOTE = "estimate only, not a ZRA filing"
