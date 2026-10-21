"""Like through YouTube's accessible UI, without relying on generated classes."""
import re
import time
from .media import short_id

LIKE_NAME = re.compile(r'^(?:like|unlike|remove like)(?:\s|$)', re.I)


def like_short(page, url, stopped=lambda: False, timeout=5):
    expected = short_id(url)
    def outcome(status, message):
        return {'status': status, 'message': message}
    def correct_video():
        return expected and short_id(page.url) == expected
    def signed_out():
        for role in ('link', 'button'):
            for item in page.get_by_role(role, name=re.compile(r'^sign in$', re.I)).all():
                if item.is_visible():
                    return True
        return False
    try:
        if stopped():
            return outcome('cancelled', 'Stopped before liking.')
        if not correct_video():
            return outcome('wrong_video', 'The browser moved to another video; no like was attempted.')
        # Only use a unique button actually on screen. Offscreen Shorts may keep
        # their buttons in the DOM. Keep its element handle so a re-render cannot
        # silently retarget a locator at another video.
        until = time.monotonic() + timeout
        button = None
        while time.monotonic() < until:
            if stopped():
                return outcome('cancelled', 'Stopped before liking.')
            if not correct_video():
                return outcome('wrong_video', 'The browser moved to another video.')
            viewport = page.evaluate('({width:innerWidth,height:innerHeight})')
            candidates = []
            for handle in page.get_by_role('button', name=LIKE_NAME).element_handles():
                box = handle.bounding_box()
                if box and handle.is_visible() and 0 <= box['x'] + box['width']/2 < viewport['width'] and 0 <= box['y'] + box['height']/2 < viewport['height']:
                    candidates.append(handle)
            if len(candidates) > 1:
                return outcome('ambiguous', 'More than one like button is on screen; no click was made.')
            if candidates:
                button = candidates[0]
                break
            page.wait_for_timeout(200)
        if button is None:
            return outcome('not_found', 'Could not identify the like button. YouTube may have changed its labels; English labels are currently supported.')
        pressed = button.get_attribute('aria-pressed')
        if pressed == 'true':
            return outcome('already_liked', 'Already liked on YouTube.')
        if pressed != 'false':
            return outcome('unknown_state', 'The button’s like state is unclear; no click was made.')
        if signed_out():
            return outcome('needs_sign_in', 'Sign in to YouTube in the watching browser to enable real likes.')
        if button.is_disabled() or button.get_attribute('aria-disabled') == 'true':
            return outcome('disabled', 'YouTube disabled the like button.')
        if stopped() or not correct_video():
            return outcome('cancelled', 'The video changed or watching stopped before the click.')
        button.click(timeout=3000)  # One click only; never toggle a liked video off.
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if not correct_video():
                return outcome('unconfirmed', 'The page changed after the click; the like could not be confirmed.')
            if button.get_attribute('aria-pressed') == 'true':
                return outcome('liked', 'Liked on YouTube.')
            if signed_out():
                return outcome('needs_sign_in', 'YouTube requires sign-in to save the like.')
            if stopped():
                return outcome('unconfirmed', 'Stopped after the click, before confirmation.')
            page.wait_for_timeout(200)
        return outcome('unconfirmed', 'Clicked once, but YouTube did not confirm the like. No retry was made.')
    except Exception as exc:
        return outcome('unconfirmed', 'Could not confirm the like: ' + str(exc).split('Call log:')[0][:300])
