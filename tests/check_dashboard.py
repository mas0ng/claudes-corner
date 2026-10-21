"""Browser checks against a running local app; consent state is simulated."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright

if __name__ == '__main__':
    output=Path('.runtime')
    output.mkdir(exist_ok=True)
    connection=json.loads((output/'server.json').read_text(encoding='utf-8'))
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1280,'height':900},bypass_csp=True)
        errors=[]
        page.on('pageerror',lambda error: errors.append(str(error)))
        page.goto(connection['url'])
        page.locator('.card').first.wait_for()
        assert page.get_by_role('button',name='Watch Shorts').count()==1
        assert page.locator('#export, #mode, #count, #minutes').count()==0
        for image in page.locator('.frame img').all()[:5]:
            image.scroll_into_view_if_needed()
            image.evaluate('(img)=>img.decode()')
        page.locator('.frame').first.click()
        assert page.locator('dialog').evaluate('(d)=>d.open')
        page.get_by_role('button',name='Close image').click()
        page.locator('.transcript summary').first.click()
        page.wait_for_timeout(1500)
        assert page.locator('.transcript').first.evaluate('(d)=>d.open')
        page.screenshot(path=str(output/'simple-desktop.png'),full_page=True)
        videos=page.request.get(connection['url']+'/api/library').json()
        fixture=dict(videos[0], reaction='Dashboard feedback test.', feedback={
            'rating':5,'would_like':True,'would_comment':True,'comment':'What a reveal! (UI test fixture)'})
        page.route('**/api/library',lambda route:route.fulfill(json=[fixture]))
        page.get_by_text('5/5 · Loved it',exact=True).wait_for()
        assert page.get_by_text('♥ Would like',exact=True).is_visible()
        assert page.get_by_text('Would comment',exact=True).is_visible()
        assert page.get_by_text('What a reveal! (UI test fixture)',exact=True).is_visible()
        page.screenshot(path=str(output/'feedback-preview.png'))
        fixture['feedback']={'rating':2,'would_like':False,'would_comment':False,'comment':''}
        page.get_by_text('2/5 · Not keen',exact=True).wait_for()
        assert page.get_by_text('♡ Would not like',exact=True).is_visible()
        assert page.locator('.suggested-comment').count()==0
        page.unroute('**/api/library')
        blocker={'running':True,'status':'YouTube needs your consent','blocker':{'title':'YouTube needs your consent','message':'Review YouTube policies in the browser window.'}}
        page.route('**/api/state',lambda route:route.fulfill(json=blocker))
        page.locator('#consent').wait_for(state='visible')
        assert page.locator('main').evaluate('(m)=>m.inert')
        page.screenshot(path=str(output/'consent-warning.png'))
        page.unroute('**/api/state')
        page.locator('#consent').wait_for(state='hidden')
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(output/'simple-mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors,errors
        print('Dashboard passed: frames, transcript, ratings, like/comment previews, consent, mobile; no JS errors.')
        browser.close()
