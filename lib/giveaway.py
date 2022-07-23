import asyncio
import getpass
import logging
import json
import re
import numpy
import base64
from pyppeteer import launch, errors
from lib.prize import GiveAwayPrize
from colorama import init, Fore, Back, Style
from tinydb import TinyDB, Query
from bs4 import BeautifulSoup

db = TinyDB('db.json')

init(autoreset=True)
BASE_URL = 'https://www.amazon.com/ga/giveaways?pageId='
RANDOM_VAL = [7, 3, 2, 5, 10, 9, 6]
#RANDOM_PAGE = list(range(1,100))

query = Query()

def is_it_in_there(url):
    result = db.search((query.url == url) & (query.visited == 1))
    if len(result) == 1:
        # print(result)
        return True
    
def check_and_insert(url):
    result = db.search(query.url == url)
    if len(result) == 0:
        db.insert({'url': url, 'visited': 0})

def get_key_token(prize_page):
    regex = r"^.*#invalidateRequirementCallbackToken\"\).val\(\"(.*)\".*$"
    test_str = prize_page
    matches = re.finditer(regex, test_str, re.MULTILINE)
    for matchNum, match in enumerate(matches):
        matchNum = matchNum + 1
        return match[1]

def get_key_stamp(prize_page):
    regex = r"^.*#invalidateRequirementCallbackTimestamp\"\).val\(\"(.*)\".*$"
    test_str = prize_page
    matches = re.finditer(regex, test_str, re.MULTILINE)
    for matchNum, match in enumerate(matches):
        matchNum = matchNum + 1
        return match[1]        

def visit_page(url):
    db.update({'visited': 1}, query.url == url)
    result = db.search(query.visited == 0)
    if len(result) == 0:
        result = db.all()
        check_and_insert(url)
        # index = int(result[-1]["url"].split(BASE_URL)[1])
        # url = BASE_URL + str(index + 1)


        
class GiveAwayBot(object):
    def __init__(self):
        self.email = None
        self.password = None
        self.browser = None
        self.current_url = None
        self.ga_prizes = {}


    async def _nav_to_ga(self, login_page):
        await login_page.goto('https://www.amazon.com/ga/giveaways')
        return login_page

    async def login(self, init=True):
        email_input_box = '#ap_email'
        password_input_box = '#ap_password'
        #remember_me = '#rememberMe'
        sign_in_button = '#signInSubmit'

        async def get_browser():
            return await launch(headless=False)

        async def check_for_continue(login_page):
            continue_button = '#continue'
            is_continue_present = await login_page.querySelector(continue_button)
            if is_continue_present:
                await login_page.click(continue_button)

        login_msg = f'{Fore.LIGHTYELLOW_EX}Log into Amazon...'
        print(login_msg)
        if init:
            email_msg = 'Enter your Amazon email address: '
            pass_msg = 'Enter your Amazon password: '
            self.email = input(email_msg)
            self.password = getpass.getpass(pass_msg)
        self.browser = await get_browser()
        login_page = await self.browser.newPage()
        await login_page.setViewport({'width': 1900, 'height': 1000})
        await login_page.goto(
            'https://www.amazon.com/ap/signin?_encoding=UTF8&ignoreAuthState=1&openid.assoc_handle=usflex&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.mode=checkid_setup&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0&openid.ns.pape=http%3A%2F%2Fspecs.openid.net%2Fextensions%2Fpape%2F1.0&openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.amazon.com%2Fgp%2Fgiveaway%2Fhome%2Fref%3Dnav_custrec_signin&switch_account='
            )
        await login_page.type(email_input_box, self.email)
        await check_for_continue(login_page)
        await login_page.waitForSelector(password_input_box, timeout=5000)
        await login_page.type(password_input_box, self.password)
        #await self.browser.click(remember_me)
        await login_page.click(sign_in_button)
        await asyncio.sleep(2)
        # this will navigate to root Giveaway page after successful login and return the page.
        ga_page = await self._nav_to_ga(login_page)
        await asyncio.sleep(2)
        return ga_page
        #await self.browser.close()

    async def get_page_giveaways(self, ga_page):
        giveaway_grid_selector = '#giveaway-grid'
        giveaway_grid = await ga_page.querySelector(giveaway_grid_selector)
        if giveaway_grid:
            page_giveaways = await giveaway_grid.xpath('*/*')
            return page_giveaways
        else:
            return None

    def display_ga_process(self, ga_name):
        ga_process = Fore.CYAN + Style.BRIGHT + 'Processing GiveAway:{0}  {1}'.format(Style.RESET_ALL, ga_name)
        print(ga_process)

    #checks if the giveaway requires a follow
    async def check_for_follow(self, prize_page):
        ga_follow_element = await prize_page.querySelector('.qa-amazon-follow-text')
        if not ga_follow_element:
            return False
        msg = Fore.RED + Style.BRIGHT + "    **** Giveaway requires a follow. ****"
        print(msg)
        return True

    async def check_for_entered(self, prize_page, deep):
        #await prize_page.waitForSelector('.qa-giveaway-result-text')
        ga_result_element = await prize_page.querySelector('.qa-giveaway-result-text')
        ended = await prize_page.querySelector('.giveaway-ended-header')
        print(deep)
        # print(is_it_in_there(deep))
        if is_it_in_there(deep):
            msg = Fore.RED + Style.BRIGHT + "    **** Already entered giveaway in the database. ****"
            print(msg)
            return True
        if ga_result_element:
            ga_result = await prize_page.evaluate(
                '(ga_result_element) => ga_result_element.textContent',
                ga_result_element
            )
            if "didn't win" in ga_result:
                msg = Fore.MAGENTA + Style.BRIGHT + "    **** Already entered giveaway and you didn't win. ****"
                print(msg)
                return True
            elif "entry has been received" in ga_result:
                msg = Fore.LIGHTMAGENTA_EX + Style.BRIGHT + "  **** You submitted an entry to this giveaway. ****"
                print(msg)  
                return True              
            elif ended:
                msg = Fore.LIGHTMAGENTA_EX + Style.BRIGHT + "  **** Giveaway Ended :(  ****"
                print(msg)                            
            return True

        else:
            return False
    
    async def display_ga_result(self, prize_page):
        await prize_page.waitForSelector('.qa-giveaway-result-text')
        ga_result_element = await prize_page.querySelector('.qa-giveaway-result-text')
        ga_result = await prize_page.evaluate(
            '(ga_result_element) => ga_result_element.textContent',
            ga_result_element
        )
        if "didn't win" in ga_result:
            msg = Fore.YELLOW + Style.BRIGHT + "  **** You entered the giveaway but did not win. ****"
        elif "entry has been received" in ga_result:
            msg = Fore.LIGHTMAGENTA_EX + Style.BRIGHT + "  **** You submitted an entry to this giveaway. ****"
        else:
            msg = Fore.GREEN + Style.BRIGHT + "   **** Maybe you won?? ****"    

        print(msg)    

    async def no_req_giveaways(self):
        try:
            for prize in self.ga_prizes:
                if self.ga_prizes[prize]['Entered'] is False:
                    self.display_ga_process(self.ga_prizes[prize]['Name'])
                    prize_page = await self.browser.newPage()
                    await prize_page.setViewport({'width': 1400, 'height': 800})
                    await prize_page.goto(self.ga_prizes[prize]['Url'])
                    # print(self.ga_prizes[prize]['Url'])
                    deep = self.ga_prizes[prize]['Url']
                    # testing a random sleep methodology to avoid bot detection / captcha.
                    ga_follow = await self.check_for_follow(prize_page)
                    if ga_follow is True:
                        msg = Fore.MAGENTA + Style.BRIGHT + "    **** Closing follow giveaway page. ****"
                        print(msg)
                        await asyncio.sleep(1)
                    else:
                        ga_entry = await self.check_for_entered(prize_page,deep)
                        if ga_entry is False:
                            await asyncio.sleep(numpy.random.choice(RANDOM_VAL))
                            prize_box = await prize_page.querySelector('#box_click_target')
                            enter_button = await prize_page.querySelector('#enterSubmitForm')
                            enter_video = await prize_page.querySelector('#videoSubmitForm')
                            video_text = await prize_page.querySelector('#giveaway-youtube-video-watch-text')
                            book = await prize_page.querySelector('#submitForm')
                            play_airy = await prize_page.querySelector('.airy-play')
                            video_form = await prize_page.querySelector('#videoSubmitForm')
                            continue_button = await prize_page.querySelector("input[name='continue']")
                            sub_button = await prize_page.querySelector("input[name='subscribe']")
                            enter = await prize_page.querySelector("input[name='enter']")
                            subscribe = await prize_page.querySelector("#ts_en_ns_subscribe")
                            #follow_button = await prize_page.querySelector('#ts_en_fo_follow')
                            string_val = await prize_page.content()
                            #print("Key:")
                            #print("Key ^")
                            if prize_box:
                                await asyncio.sleep(numpy.random.choice(RANDOM_VAL))
                                await prize_box.click()
                                msg = Fore.MAGENTA + Style.BRIGHT + "    **** I clicked the prize box. ****"
                                print(msg)
                            elif enter_button:
                                    await enter_button.click()
                            elif book:
                                    await book.click()
                            elif video_text:
                                    msg = Fore.MAGENTA + Style.BRIGHT + "    **** Waiting 30 seconds. ****"
                                    print(msg)
                                    await asyncio.sleep(28)
                                    msg2 = Fore.MAGENTA + Style.BRIGHT + "    **** 30 Seconds is over, Entering Contest. ****"
                                    print(msg2)                        
                                    await enter_video.click()
                            elif subscribe:
                                    msg = Fore.MAGENTA + Style.BRIGHT + "    **** An Amazon sponsored giveaway. ****"
                                    print(msg)
                                    await sub_button.click()
                                    await asyncio.sleep(2)
                                    await enter.click()
                            elif play_airy:
                                print(get_key_token(string_val))
                                print(get_key_stamp(string_val))
                                token = get_key_token(string_val)
                                stamp = get_key_stamp(string_val)
                                btoken = base64.urlsafe_b64encode(token.encode('UTF-8')).decode('ascii')
                                bstamp = base64.urlsafe_b64encode(stamp.encode('UTF-8')).decode('ascii')
                                # soup_token = BeautifulSoup(string_val)
                                # soup_stamp = BeautifulSoup(string_val)
                                # soup_t = soup_token.find('input', {"id": "invalidateRequirementCallbackToken"})
                                # soup_t['value'] = ""
                                # print(soup_t)
                                # soup_s = soup_stamp.find('input', {"id": "invalidateRequirementCallbackTimestamp"})
                                # soup_s['value'] = ""
                                # print(soup_s)                            
                                # print(soup_token)
                                # print(soup_stamp)
                                # http://pugstatus.com/test.js
                                # https://code.jquery.com/jquery-3.3.1.min.js
                                msg = Fore.MAGENTA + Style.BRIGHT + "    **** Amazon Video: Loading external javascript, bypassing video watching. ****"
                                print(msg)
                                await prize_page.addScriptTag(url='https://code.jquery.com/jquery-3.3.1.min.js')
                                await prize_page.addScriptTag(
                                    url=f'https://pugstatus.com/ago.php?token={btoken}&stamp={bstamp}'
                                )

                                #await asyncio.sleep(2)
                                # prize_page.querySelector('invalidateRequirementCallbackToken').value = get_key_token(string_val)
                                # prize_page.querySelector('invalidateRequirementCallbackTimestamp').value = get_key_stamp(string_val)
                                msg = Fore.MAGENTA + Style.BRIGHT + "    **** Amazon Video, Watching 30 sec then click giveaway. ****"
                                print(msg)
                                await play_airy.click()
                                msg = Fore.MAGENTA + Style.BRIGHT + "    **** Waiting 30 seconds. ****"
                                print(msg)
                                await asyncio.sleep(32)
                                await continue_button.click()
                                msg = Fore.MAGENTA + Style.BRIGHT + "    **** 30 Seconds is over, Entering Contest. ****"
                                print(msg)
                            else:
                                await asyncio.sleep(1)
                                await prize_page.close()
                                msg = Fore.MAGENTA + Style.BRIGHT + "    **** Timed out :: Close page. ****"
                                print(msg)
                            await asyncio.sleep(numpy.random.choice(RANDOM_VAL))
                            await self.display_ga_result(prize_page)
                            await asyncio.sleep(1)
                            check_and_insert(self.ga_prizes[prize]['Url'])
                            # enter the url here as visited
                            visit_page(self.ga_prizes[prize]['Url'])
                        else:
                            msg = Fore.MAGENTA + Style.BRIGHT + "    **** All checks have been reached, moving on to next giveaway ****"
                            print(msg)
                            await asyncio.sleep(1)
                    await prize_page.close()
        except errors.NetworkError as e:
            msg = Fore.MAGENTA + Style.BRIGHT + "    **** Not sure what happened, skipping. ****"
            print(msg)
            await asyncio.sleep(1)                     
            await prize_page.close()
                    
    async def check_for_last_page(self, ga_page):
        last_page = await ga_page.xpath("//li[@class='a-disabled a-last']")
        if not last_page:
            return False
        msg = Fore.LIGHTWHITE_EX + Style.BRIGHT + "**** The Last GiveAway Page has been reached.  Exiting... ****"
        print(msg)
        return True

    async def iterate_page(self, ga_page):
        try:
            next_page = await ga_page.xpath("//li[@class='a-last']")
            if next_page:
                next_page_href = await ga_page.evaluate(
                    '(next_page) => next_page.firstChild.href',
                    next_page[0]
                )
                msg = (
                    Fore.LIGHTGREEN_EX
                    + Style.BRIGHT
                    + f"**** Moving to next giveaway page -> {next_page_href}... ****"
                )

                print(msg)
                await ga_page.goto(next_page_href)
                return ga_page
            else:
                msg = Fore.LIGHTRED_EX + Style.BRIGHT + "**** Could not find Next Page for GiveAways, Exiting... ****"
                print(msg)
                quit(1)
        except errors.PageError:
            ""
            
    async def process_giveaways(self, ga_page):

        async def create_ga_prize(giveaway):

            def parse_prize_url(url):
                ga_url = re.search(r'(^.*)(?=\?)', url)
                return ga_url[0]

            prize_name_element = await giveaway.querySelector('.giveawayPrizeNameContainer')
            prize_name = await ga_page.evaluate(
                '(prize_name_element) => prize_name_element.textContent',
                prize_name_element
            )
            prize_req_element = await giveaway.querySelector('.giveawayParticipationInfoContainer')
            prize_req = await ga_page.evaluate(
                '(prize_req_element) => prize_req_element.textContent',
                prize_req_element
            )
            prize_href = await ga_page.evaluate(
                '(giveaway) => giveaway.href',
                giveaway
            )
            prize_url = parse_prize_url(prize_href)
            ga_prize = GiveAwayPrize()
            ga_prize.set_prize_name(prize_name)
            ga_prize.set_prize_req(prize_req)
            ga_prize.set_prize_url(prize_url)
            self.ga_prizes[len(self.ga_prizes)] = {
                'Name': ga_prize.get_prize_name(),
                'Requirement': ga_prize.get_prize_req(),
                'Url': ga_prize.get_prize_url(),
                'Entered': False
            }
                #print(prize_url)

        page_giveaways = await self.get_page_giveaways(ga_page)
        if page_giveaways:
            for giveaway in page_giveaways:
                await create_ga_prize(giveaway)
            await self.no_req_giveaways()
        else:
            print('*** no giveaways returned ***')
