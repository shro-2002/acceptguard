"""Every legal interpretation the date logic depends on. A CA should review each [CA] item.

[CA-1] The 15-day objection window excludes the delivery day (General Clauses Act s.9),
       so the last valid day is delivery + 15.
[CA-2] Email, letter and WhatsApp records count as "in writing" (IT Act s.4).
[CA-3] Payment after year-end but within the MSMED s.15 limit is allowed in the year
       (majority practitioner view; not confirmed by CBDT).
[CA-4] An agreement with no stated credit basis counts from the invoice date.
[CA-5] An agreed date earlier than the acceptance day is routed to the CA (law unclear).
[CA-6] No weekend or holiday shift: the MSMED Act has no such provision.
[CA-7] Trader exclusion from s.43B(h) is unsettled: trader category is routed to the CA.
"""

OBJECTION_WINDOW_DAYS = 15  # [CA-1] MSMED s.2(b) Explanation
NO_AGREEMENT_PAYMENT_DAYS = 15  # MSMED s.15 with s.2(b): pay before the appointed day (A + 16)
MAX_AGREED_DAYS = 45  # MSMED s.15 proviso
UNSPECIFIED_BASIS = "invoice"  # [CA-4]
WRITTEN_MEDIA = frozenset({"email", "letter", "whatsapp"})  # [CA-2]
COMPUTED_CATEGORIES = frozenset({"micro", "small"})  # s.43B(h) covers micro and small enterprises only
OUT_OF_SCOPE_CATEGORIES = frozenset({"medium", "unregistered"})  # anything else, e.g. trader, is [CA-7]
PAID_AFTER_YEAR_END_WITHIN_LIMIT_ALLOWED = True  # [CA-3]
