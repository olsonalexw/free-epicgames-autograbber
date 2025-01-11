import json
from json.decoder import JSONDecodeError
import logging
import os
import pyotp
import time
import traceback
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, \
    NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options


FREE_GAMES_PAGE_URL = 'https://www.epicgames.com/store/en-US/free-games/'


def read_env_variables():
    global TIMEOUT, EMAIL, PASSWORD, LOGLEVEL, SLEEPTIME, TOTP, DEBUG

    # dev environment
    DEBUG = os.getenv('DEBUG') is not None

    value = os.getenv('TIMEOUT') or 20
    TIMEOUT = int(value)

    EMAIL = os.getenv('EMAIL') or ''
    PASSWORD = os.getenv('PASSWORD') or ''
    LOGLEVEL = str.upper(os.getenv('LOGLEVEL') or '')
    SLEEPTIME = int(os.getenv('SLEEPTIME') or -1)
    value = os.getenv('TOTP') or None
    TOTP = None if value is None else pyotp.TOTP(value)


def load_cookies(chrome_driver):
    logger.debug("trying to load cookies")
    try:
        with open('cookies.json', 'r') as cookies_file:
            for i in json.load(cookies_file):
                try:
                    chrome_driver.add_cookie(
                        {
                            "name": i['name'],
                            "value": i['value'],
                            "domain": i['domain']
                        }
                    )
                except (WebDriverException, KeyError):
                    pass
            logger.debug("all cookies loaded, refreshing the page")
            chrome_driver.refresh()
    except FileNotFoundError:
        logger.critical('cookies file not found')
    except JSONDecodeError:
        logger.critical('cookies file not correctly formatted')


def open_browser():
    chrome_options = Options()
    # bypass OS security model
    chrome_options.add_argument('--no-sandbox')
    # overcome limited resource problems
    chrome_options.add_argument('--disable-dev-shm-usage')
    # path when run inside of docker container
    chrome_driver_path = '/usr/bin/chromedriver'

    if DEBUG:
        chrome_driver_path = './chromedriver'
        # window size when run in headless mode.
        # this is necessary as some styles are dynamic
        chrome_options.add_argument('--window-size=800,600')
    else:
        chrome_options.add_argument('--headless')

    return webdriver.Chrome(chrome_driver_path, options=chrome_options)


def purchase_steps(browser):

    try:
        # Search for license agreement popup and click it
        logger.debug("find and accept license agreement")
        WebDriverWait(browser, TIMEOUT).until(
            EC.visibility_of_element_located((
                By.ID,
                "agree"
            ))
        ).click()

        # Search and click Accept button
        WebDriverWait(browser, TIMEOUT).until(
            EC.visibility_of_element_located((
                By.XPATH,
                "//button[descendant::span[text()='Accept']]"
            ))
        ).click()

        # Click again the purchase button
        logger.debug('find and clicking again the purchase button')
        WebDriverWait(browser, TIMEOUT).until(
            EC.visibility_of_element_located((
                By.XPATH,
                "//button[@data-testid='purchase-cta-button']"
            ))
        ).click()

    except TimeoutException:
        logger.debug("no license agreement found")

    # wait until its visible and then click the purchase button
    logger.debug('find and click on the last purchase button')
    WebDriverWait(browser, TIMEOUT).until(
        EC.visibility_of_element_located((
            By.XPATH,
            "//button[contains(@class,'btn-primary')]"
        ))
    ).click()

    # wait until its visible and then click the 'I Agree" popup
    # 'Refund and Right of Withdrawal Information' popup
    try:
        logger.debug('accept the conditions of refund popup')
        WebDriverWait(browser, TIMEOUT).until(
            EC.visibility_of_all_elements_located((
                By.XPATH,
                "//button[contains(@class,'btn-primary')]"
            ))
        )[1].click()

    except (NoSuchElementException, TimeoutException, LookupError):
        logger.debug('no refund conditions popup to accept')

    logger.debug('Wait for confirmation that checkout is complete')

    # Purchase should be complete. Checking for confirmation
    WebDriverWait(browser, TIMEOUT).until(
        EC.visibility_of_element_located((
            By.XPATH,
            "//h1/span[contains(text(),'Install')]|"
            "//span[contains(text(),'Thank you for buying')]"
        ))
    )


def login(browser):
    try:
        logger.debug('find and click on login button')
        el = WebDriverWait(browser, TIMEOUT).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//div[@id='user']"
            ))
        )
        el.click()

        logger.debug('find and click on EpicGame login method')
        el = WebDriverWait(browser, TIMEOUT).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//div[@id='login-with-epic']"
            ))
        )
        el.click()

        logger.debug('wait for email field on login page')
        el = WebDriverWait(browser, TIMEOUT).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//input[@id='email']"
            ))
        )

        el.send_keys(EMAIL)
        browser.find_element_by_xpath(
            "//input[@id='password']"
        ).send_keys(PASSWORD)

        WebDriverWait(browser, TIMEOUT).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//button[@id='sign-in']"
            ))
        ).click()

    except TimeoutException:
        logger.critical("Unable to locate login form")

    try:
        logger.debug('Checking for captcha')
        WebDriverWait(browser, TIMEOUT).until(
            EC.presence_of_element_located((
                By.XPATH,
                '//iframe[@id="talon_frame_login_prod"]'
            ))
        )
        logger.critical('Captcha found. Can\'t procede any further.')
        browser.close()
        exit(0)

    except TimeoutException:
        logger.debug('captcha not detected.')

    if TOTP is not None:
        logger.debug('wait for 2fa field on login page')
        el = WebDriverWait(browser, TIMEOUT).until(
            EC.element_to_be_clickable((By.ID, "code"))
        )
        el.send_keys(TOTP.now())
        logger.debug('logging in with 2FA')
        browser.find_element_by_id('continue').click()

    try:
        # confirm login
        logger.debug('search for wrong credentials message')
        WebDriverWait(browser, TIMEOUT).until(
            EC.visibility_of_element_located((
                By.XPATH,
                "//h6[contains(text(),'credentials') "
                "and contains(text(),'invalid')]"
            ))
        )

        logger.critical(
            'failed to login into account, credentials invalid'
        )
        browser.close()
        exit(0)
    except TimeoutException:
        logger.debug('login succeeded')
        pass


def execute():
    browser = open_browser()
    browser.get(FREE_GAMES_PAGE_URL)
    load_cookies(browser)

    # Am I logged in?
    try:
        # If there's the logout button then I'm logged in
        browser.find_element_by_xpath("//a[@id='log-out']/span")
    except NoSuchElementException:
        # Else I have to login
        login(browser)

    try:
        try:
            # get free games available
            logger.debug('wait for and get all free games available')
            games_found = WebDriverWait(browser, TIMEOUT).until(
                EC.visibility_of_all_elements_located((
                    By.XPATH,
                    "//a[descendant::span[text()='Free Now']]"
                ))
            )
        except TimeoutException:
            logger.critical('no free games found')
            return

        try:
            logger.debug('close the cookies banner')
            # close cookie policy span as it interferes
            # with clicking on the purchase button
            WebDriverWait(browser, TIMEOUT).until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//div[@id='onetrust-close-btn-container']/button"
                ))
            ).click()
        except NoSuchElementException:
            logger.debug('no cookies banner to close')

        for i in range(len(games_found)):
            logger.debug('wait for and get all free games available')
            games_found = WebDriverWait(browser, TIMEOUT).until(
                EC.visibility_of_all_elements_located((
                    By.XPATH,
                    "//a[descendant::span[text()='Free Now -']]"
                ))
            )

            games_found[i].click()

            # mature content block
            logger.debug('bypass mature content block')
            try:
                WebDriverWait(browser, TIMEOUT).until(
                    EC.visibility_of_element_located((
                        By.XPATH,
                        "//span[contains(text(),'mature content')]"
                    ))
                )

                WebDriverWait(browser, TIMEOUT).until(
                    EC.visibility_of_element_located((
                        By.XPATH,
                        "//button[contains(text(),'Continue')]"
                    ))
                ).click()

            except TimeoutException:
                logger.debug('no mature content block to bypass')

            logger.debug('find the purchase button')
            purchase_button = WebDriverWait(browser, TIMEOUT).until(
                EC.visibility_of_element_located((
                    By.XPATH,
                    "//button[@data-testid='purchase-cta-button']"
                ))
            )

            # name of the game
            logger.debug('extract game title')
            name = browser.find_element_by_xpath(
                "//h2[contains(@class,'NavigationVertical')]"
            ).text

            # price formatted as '£11.99'
            logger.debug('extract game price')
            price = browser.find_element_by_xpath("//s").text

            # date formatted as 'Sale ends 11/29/2019 at 3:59 PM'
            logger.debug('extract sales end date')
            expires = browser.find_element_by_xpath(
                "//span[contains(text(),'Sale ends')]"
            ).text

            if purchase_button.text == 'OWNED':
                logger.info(
                    '\"%s\" already owned. Price was %s and %s',
                    name, price, expires
                )

            elif purchase_button.text == 'GET':
                logger.info('obtaining \"%s\"', name)
                purchase_button.click()

                purchase_steps(browser)

                logger.info(
                    'obtained %s. Price was %s and %s',
                    name, price, expires
                )

            elif purchase_button.text == 'SEE EDITIONS':
                logger.debug('processing editions for \"%s\"', name)
                # used to know the number of elements and titles
                # without having to query on every refresh
                editions_addons_titles = WebDriverWait(browser, TIMEOUT).until(
                    EC.visibility_of_all_elements_located((
                        By.XPATH, "//div[contains(@class,'Editions-title') "
                                  "or contains(@class, 'AddOns-title')]"
                    ))
                )

                addons_titles = [i.text for i in editions_addons_titles]

                for t in range(len(addons_titles)):
                    editions_addons_buttons = WebDriverWait(browser, TIMEOUT)

                    editions_addons_buttons.until(
                        EC.visibility_of_all_elements_located((
                            By.XPATH,
                            "//div[contains(@class,'Editions') or contains("
                            "@class, 'AddOns')]//div[contains("
                            "@class,'PurchaseButton-ctaButtons')]//button"
                        ))
                    )

                    if editions_addons_buttons[t].text == 'OWNED':
                        logger.info(
                            '\"%s - %s\" already owned',
                            name, addons_titles[t]
                        )

                    elif editions_addons_buttons[t].text == 'GET':
                        editions_addons_buttons[t].click()

                        purchase_steps(browser)

                        logger.info('obtained \"%s - %s\"',
                                    name, addons_titles[t])

                        browser.execute_script("window.history.go(-1)")
            else:
                logger.warning(
                    'purchase button text not recognized: %s',
                    purchase_button.text
                )

            # navigate back to free games page
            browser.get(FREE_GAMES_PAGE_URL)
        logger.info('all games processed')
    except (TimeoutException, NoSuchElementException, WebDriverException):
        logger.critical(traceback.format_exc())
    browser.close()


def main():
    global logger
    logger = logging.getLogger('egs-weekly-freegames')
    read_env_variables()
    logging.basicConfig(level=logging.ERROR)
    logger.setLevel(getattr(logging, LOGLEVEL, "INFO"))
    if EMAIL == "" or PASSWORD == "":
        print('credentials missing')
        return
    logger.debug(
        'started with TIMEOUT: %i, EMAIL: %s, password: %s',
        TIMEOUT, EMAIL, len(PASSWORD) * "*",
    )
    execute()
    while SLEEPTIME >= 0:
        logger.info('sleeping for %i seconds', SLEEPTIME)
        time.sleep(SLEEPTIME)
        execute()


if __name__ == '__main__':
    main()
