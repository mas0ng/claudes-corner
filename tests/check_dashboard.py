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
        page.context.grant_permissions(['clipboard-read','clipboard-write'],origin=connection['url'])
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
            'rating':5,'would_like':True,'would_comment':True,'comment':'What a reveal! (UI test fixture)'},
            like_action={'status':'liked','message':'Liked on YouTube.'})
        page.route('**/api/library',lambda route:route.fulfill(json=[fixture]))
        page.get_by_text('5/5 · Loved it',exact=True).wait_for()
        assert page.locator('#stat-enjoyment').inner_text()=='5.0/5'
        assert page.locator('#stat-happiness').inner_text()=='100%'
        assert page.locator('#stat-likes').inner_text()=='1/1'
        assert page.locator('#stat-comments').inner_text()=='1/1'
        assert page.get_by_role('img',name='AI would like this video',exact=True).is_visible()
        assert page.locator('.like-divider').is_visible()
        assert page.locator('.like-heart').evaluate('(n)=>getComputedStyle(n).color')=='rgb(180, 73, 118)'
        assert page.get_by_text('♥ Liked on YouTube',exact=True).count()==0
        assert page.locator('#auto-like').count()==0
        assert page.get_by_text('Comment draft',exact=True).is_visible()
        assert page.get_by_text('Not posted',exact=True).is_visible()
        assert page.locator('.star.filled').count()==5
        assert page.get_by_role('img',name='5 out of 5 stars').is_visible()
        assert page.get_by_text('What a reveal! (UI test fixture)',exact=True).is_visible()
        page.get_by_role('button',name='Copy comment',exact=True).click()
        page.get_by_role('button',name='Copied',exact=True).wait_for()
        assert page.evaluate('navigator.clipboard.readText()')=='What a reveal! (UI test fixture)'
        page.evaluate('scrollTo(0,350)')
        assert 0 <= page.locator('.stats-wrap').bounding_box()['y'] <= 13
        page.evaluate('scrollTo(0,0)')
        page.screenshot(path=str(output/'feedback-preview.png'),full_page=True)
        fixture['feedback']={'rating':2,'would_like':False,'would_comment':False,'comment':''}
        page.get_by_text('2/5 · Not keen',exact=True).wait_for()
        assert page.locator('#stat-happiness').inner_text()=='0%'
        assert page.get_by_role('img',name='AI would not like this video',exact=True).is_visible()
        assert page.locator('.like-heart').evaluate('(n)=>getComputedStyle(n).color')=='rgb(199, 203, 195)'
        assert page.locator('.star.filled').count()==2
        assert page.locator('.star:not(.filled)').count()==3
        assert page.get_by_text('No comment',exact=True).is_visible()
        assert page.locator('.suggested-comment blockquote').count()==0
        fixture['feedback']={'rating':4,'would_like':True,'would_comment':True,'comment':'A clear draft.'}
        fixture['like_action']={'status':'needs_sign_in','message':'Sign in to YouTube to enable likes.'}
        page.get_by_text('4/5 · Liked it',exact=True).wait_for()
        assert page.get_by_text('♡ Sign in to like',exact=True).count()==0
        assert page.get_by_text('Sign in to YouTube to enable likes.',exact=True).count()==0
        page.set_viewport_size({'width':390,'height':844})
        page.evaluate('scrollTo(0,0)')
        page.screenshot(path=str(output/'feedback-mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.set_viewport_size({'width':1280,'height':900})
        page.unroute('**/api/library')
        low=dict(fixture,folder='test-low',feedback={'rating':2,'would_like':False,'would_comment':False,'comment':''})
        unrated=dict(fixture,folder='test-unrated');unrated.pop('feedback')
        page.route('**/api/library',lambda route:route.fulfill(json=[fixture,low,unrated]))
        page.wait_for_function("document.getElementById('stat-enjoyment').textContent==='3.0/5'")
        assert page.locator('#stat-happiness').inner_text()=='50%'
        assert page.locator('#stat-likes').inner_text()=='1/2'
        assert page.locator('#stat-comments').inner_text()=='1/2'
        assert page.locator('#stats-context').inner_text().startswith('2 rated videos')
        page.unroute('**/api/library')
        page.route('**/api/library',lambda route:route.fulfill(json=[]))
        page.wait_for_function("document.getElementById('stat-enjoyment').textContent==='—'")
        assert page.locator('#stat-happiness').inner_text()=='—'
        assert page.locator('#enjoyment-bar').get_attribute('value')=='0'
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
        print('Dashboard passed: aggregate stats, unrated/empty data, sticky bar, comment copy, stars, hearts, consent, mobile; no JS errors.')
        browser.close()
