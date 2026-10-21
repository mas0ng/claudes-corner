"""Validate the agent's hypothetical engagement, never real YouTube actions."""


def validate_feedback(value):
    if value is None:
        return None  # Older agents can still save plain chat reactions.
    if not isinstance(value, dict):
        raise ValueError('Feedback must be an object.')
    if set(value) != {'rating', 'would_like', 'would_comment', 'comment'}:
        raise ValueError('Feedback requires rating, would_like, would_comment and comment.')
    if type(value['rating']) is not int or not 1 <= value['rating'] <= 5:
        raise ValueError('Rating must be a whole number from 1 to 5.')
    if type(value['would_like']) is not bool or type(value['would_comment']) is not bool:
        raise ValueError('would_like and would_comment must be booleans.')
    if not isinstance(value['comment'], str) or len(value['comment']) > 4000:
        raise ValueError('Suggested comment must be text, up to 4000 characters.')
    comment = value['comment'].strip()
    if value['would_comment'] != bool(comment):
        raise ValueError('Provide a comment when would_comment is true; otherwise leave it empty.')
    return {**value, 'comment': comment}
