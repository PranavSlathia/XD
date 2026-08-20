# CZDS access — truthful-use guidance

Do not submit the old draft that described Domain Hunter as a non-commercial
link-rot study. The product's present purpose is commercial domain-acquisition
research, so that wording would be false.

ICANN's standard CZDS terms permit lawful use but prohibit marketing use,
harassment, unauthorized redistribution, and high-volume automated queries to
registries or registrars beyond what is reasonably necessary for registration.
They also limit CZDS downloads to once per TLD per 24 hours. A registry can
approve or deny a request and can terminate access.

Source: [ICANN CZDS Terms and Conditions](https://newgtlds.icann.org/sites/default/files/terms-conditions-30sep13-en.pdf)

## Decision for Domain Hunter

CZDS is **not required** by the current pipeline. DropCatch's public upcoming
drop file provides the acquisition inventory, and RDAP confirms lifecycle
status. This is smaller, cheaper, and better aligned with the actual product.

Do not apply for CZDS merely to make the feed larger. Apply only if there is a
real, accurately describable use that needs zone-file deltas and complies with
the registry's terms. Never hide domain investing, flipping, or another
commercial purpose behind research language.

## If a legitimate use arises

Use a short factual statement, customized to the exact project. Do not claim an
academic affiliation, non-commercial status, retention policy, security
control, or publication plan that does not exist.

Example structure—not a pre-approved legal statement:

```text
I operate an internal domain lifecycle analysis system for [truthful purpose].
I need the [TLD] zone file to [specific necessity that cannot be met by RDAP or
an existing public feed]. Access will be limited to [actual people/systems].
The data will not be used for marketing, harassment, or unsolicited contact,
and will not be redistributed. Downloads will occur no more than once per 24
hours. Data will be retained for [actual period] and protected by [actual
controls].
```

Before submitting:

1. Read the live CZDS terms and the registry-specific agreement.
2. Confirm the purpose is accurate and permitted.
3. Record the approved TLD, exact purpose, retention, and access controls in
   `source_terms`.
4. Store credentials outside Git.
5. Enforce the 24-hour download minimum in code.
6. Stop access if the use changes materially until the registry confirms it.

CZDS data must never become an outbound-marketing list.
