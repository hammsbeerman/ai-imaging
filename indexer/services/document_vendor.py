def guess_vendor_from_email(email: str) -> str:
    email = (email or '').strip().lower()
    if '@' not in email:
        return ''

    domain = email.split('@', 1)[1].strip()
    if not domain:
        return ''

    exact_map = {
        'amazon.com': 'Amazon',
        'amazonbusiness.com': 'Amazon Business',
        'ups.com': 'UPS',
        'fedex.com': 'FedEx',
        'usps.com': 'USPS',
        'staples.com': 'Staples',
        'quill.com': 'Quill',
        'essendant.com': 'Essendant',
    }
    if domain in exact_map:
        return exact_map[domain]

    for needle, label in (
        ('amazon', 'Amazon'),
        ('ups', 'UPS'),
        ('fedex', 'FedEx'),
        ('usps', 'USPS'),
        ('staples', 'Staples'),
        ('quill', 'Quill'),
        ('essendant', 'Essendant'),
    ):
        if needle in domain:
            return label

    core = domain.split('.')[0].replace('-', ' ').replace('_', ' ').strip()
    return core.title()
