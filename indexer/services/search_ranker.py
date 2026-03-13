def keyword_score(query, image):
    q = query.lower()

    score = 0

    if image.filename and q in image.filename.lower():
        score += 2

    if image.customer_name and q in image.customer_name.lower():
        score += 4

    if image.job_type and q in image.job_type.lower():
        score += 3

    if image.folder_tokens and q in image.folder_tokens.lower():
        score += 2

    return score