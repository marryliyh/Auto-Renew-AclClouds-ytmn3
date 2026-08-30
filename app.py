#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import requests
from datetime import datetime, timedelta, timezone
from seleniumbase import SB
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    WebDriverException,
    StaleElementReferenceException,
)
from selenium.webdriver.common.by import By
from zoneinfo import ZoneInfo


# ============================================================
# 配置
# ============================================================

EMAIL = os.getenv("EMAIL") or ""
PASSWORD = os.getenv("PASSWORD") or ""

TG_CHAT_ID = os.getenv("TG_CHAT_ID") or ""
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN") or ""

LOGIN_PATH = "/auth/login"

BASE_URL = "https://dash.aclclouds.com/en"
PROJECTS_URL = f"{BASE_URL}/dashboard/projects"


# ============================================================
# 时间
# ============================================================

def beijing_time_str():
    try:
        return datetime.now(
            ZoneInfo("Asia/Shanghai")
        ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now(
            timezone(timedelta(hours=8))
        ).strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# Telegram
# ============================================================

def send_telegram(message):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print(f"[Telegram disabled] {message}")
        return

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": TG_CHAT_ID,
        "text": message,
    }

    try:
        response = requests.post(
            url,
            data=data,
            timeout=10,
        )

        if response.ok:
            print(f"Telegram sent: {message[:80]}...")
        else:
            print(
                f"Telegram 返回错误: "
                f"{response.status_code} {response.text[:300]}"
            )

    except Exception as e:
        print(f"Failed to send Telegram: {e}")


# ============================================================
# URL / 登录状态
# ============================================================

def wait_for_url_change(sb, original_url, timeout=30):
    start_time = time.time()

    while time.time() - start_time < timeout:
        current_url = sb.get_current_url()

        if current_url != original_url:
            return True

        sb.sleep(0.5)

    raise Exception(
        f"等待 URL 变化超时 ({timeout}秒)，"
        f"当前仍为: {original_url}"
    )


def is_login_page(sb):
    return LOGIN_PATH in sb.get_current_url()


def is_logged_in(sb):
    current_url = sb.get_current_url()

    return (
        BASE_URL in current_url
        and LOGIN_PATH not in current_url
    )


# ============================================================
# 通用 Selenium 工具
# ============================================================

def scroll_to_selector(sb, selector):
    try:
        sb.scroll_to(selector)
    except Exception:
        pass

    sb.sleep(0.2)


def safe_click_element(sb, element, label):
    try:
        sb.driver.execute_script(
            """
            arguments[0].scrollIntoView({
                block: "center",
                inline: "center"
            });
            """,
            element,
        )

        sb.sleep(0.5)

        try:
            element.click()
            return True

        except (
            ElementClickInterceptedException,
            WebDriverException,
            StaleElementReferenceException,
        ) as e:

            print(
                f"{label} 普通点击失败，"
                f"改用 JavaScript 点击: {e}"
            )

        sb.driver.execute_script(
            "arguments[0].click();",
            element,
        )

        sb.sleep(0.5)

        return True

    except StaleElementReferenceException:
        print(f"{label} 元素已失效，需要重新定位")
        return False

    except Exception as e:
        print(f"{label} 点击失败: {e}")
        return False


def element_text(element):
    try:
        return element.text.strip()
    except Exception:
        return ""


def unique_elements(elements):
    unique = []
    seen = set()

    for element in elements:

        try:
            element_id = element.id
        except Exception:
            element_id = None

        if element_id and element_id in seen:
            continue

        if element_id:
            seen.add(element_id)

        unique.append(element)

    return unique


def find_elements(root, selector):

    if selector.startswith("/") or selector.startswith(".//"):
        by = By.XPATH
    else:
        by = By.CSS_SELECTOR

    try:
        return root.find_elements(by, selector)
    except Exception:
        return []


# ============================================================
# 日期 / 时长
# ============================================================

def extract_date_like(text):

    if not text:
        return ""

    patterns = [
        r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"
        r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?",

        r"\d{1,2}[-/]\d{1,2}[-/]\d{4}"
        r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?",
    ]

    for pattern in patterns:

        match = re.search(pattern, text)

        if match:
            return match.group(0)

    return ""


def extract_duration_like(text):

    if not text:
        return ""

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    for idx, line in enumerate(lines):

        if re.search(
            r"expires\s+in|剩余|还有",
            line,
            re.I,
        ):

            if idx + 1 < len(lines):

                candidate = lines[idx + 1]

                if (
                    extract_date_like(candidate)
                    or re.search(r"\d", candidate)
                ):

                    return re.sub(
                        r"^(?:expires\s*in|剩余|还有)"
                        r"\s*[:：]?\s*",
                        "",
                        candidate,
                        flags=re.I,
                    ).strip()

    match = re.search(
        r"(?:expires\s*in\s*)?"
        r"(\d+\s*"
        r"(?:days|day|d|j|天|日)"
        r"\s*\d*\s*"
        r"(?:hours|hour|h|小时)?)",
        text,
        re.I,
    )

    if match:
        return match.group(1).strip()

    match = re.search(
        r"\d+\s*(?:hours|hour|h|小时)",
        text,
        re.I,
    )

    if match:
        return match.group(0).strip()

    return ""


# ============================================================
# 项目名称
# ============================================================

def get_project_name(card, idx):

    selectors = [
        ".projects-card-title",
        "h1",
        "h2",
        "h3",
        "h4",
        '[class*="title"]',
        '[class*="name"]',
    ]

    for selector in selectors:

        try:

            elements = card.find_elements(
                By.CSS_SELECTOR,
                selector,
            )

            for elem in elements:

                text = element_text(elem)

                if not text:
                    continue

                if len(text) > 80:
                    continue

                lowered = text.lower()

                if "renew" in lowered:
                    continue

                if "expiry" in lowered:
                    continue

                if extract_duration_like(text):
                    continue

                return text

        except Exception:
            continue

    # ACLClouds 当前页面结构的兜底方案
    lines = [
        line.strip()
        for line in element_text(card).splitlines()
        if line.strip()
    ]

    ignored = {
        "gérer",
        "modifier",
        "supprimer",
        "renew",
        "reactivate",
        "renewal",
        "mes services",
    }

    for line in lines:

        lowered = line.lower()

        if lowered in ignored:
            continue

        if len(line) > 80:
            continue

        if extract_duration_like(line):
            continue

        if re.search(
            r"expires|expiry|expire|valid|"
            r"renew|reactivate|"
            r"续期|过期|到期",
            line,
            re.I,
        ):
            continue

        return line

    return f"项目 #{idx}"


# ============================================================
# 项目过期时间
# ============================================================

def get_project_expiry(card):

    selectors = [
        ".projects-expiry-value",
        ".projects-service-cell--expiry strong",
        '[class*="expiry"] strong',
        '[class*="expiry"] [class*="value"]',
        '[class*="expiry"]',
        '[class*="expire"]',
        '[class*="Expires"]',
    ]

    for selector in selectors:

        try:

            elements = card.find_elements(
                By.CSS_SELECTOR,
                selector,
            )

            for elem in elements:

                text = element_text(elem)

                if not text:
                    continue

                date_text = extract_date_like(text)

                if date_text:
                    return date_text

                duration_text = extract_duration_like(text)

                if duration_text:
                    return duration_text

                if len(text) <= 120:
                    return text

        except Exception:
            continue

    card_text = element_text(card)

    return (
        extract_date_like(card_text)
        or extract_duration_like(card_text)
        or "未知"
    )


# ============================================================
# Renew 按钮
# ============================================================

def find_renew_buttons(root):

    selectors = [

        # 当前 / 常见 class
        ".projects-renew-btn",

        # title
        (
            'button['
            'title*="renew"'
            ' i]'
        ),

        (
            'button['
            'title*="Renew"'
            ']'
        ),

        # aria-label
        (
            'button['
            'aria-label*="renew"'
            ' i]'
        ),

        (
            'button['
            'aria-label*="Renew"'
            ']'
        ),

        (
            'button['
            'aria-label*="reactivate"'
            ' i]'
        ),

        (
            'button['
            'aria-label*="Reactivate"'
            ']'
        ),

        # XPath - 文字
        (
            './/button['
            'contains('
            'translate(normalize-space(.),'
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            '"abcdefghijklmnopqrstuvwxyz"),'
            '"renew"'
            ')'
            ']'
        ),

        (
            './/button['
            'contains('
            'translate(normalize-space(.),'
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            '"abcdefghijklmnopqrstuvwxyz"),'
            '"reactivate"'
            ')'
            ']'
        ),

        # XPath - title
        (
            './/button['
            'contains('
            'translate(@title,'
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            '"abcdefghijklmnopqrstuvwxyz"),'
            '"renew"'
            ')'
            ']'
        ),

        # XPath - aria-label
        (
            './/button['
            'contains('
            'translate(@aria-label,'
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            '"abcdefghijklmnopqrstuvwxyz"),'
            '"renew"'
            ')'
            ']'
        ),

        (
            './/*[@role="button" and '
            'contains('
            'translate(normalize-space(.),'
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            '"abcdefghijklmnopqrstuvwxyz"),'
            '"renew"'
            ')]'
        ),

        (
            './/*[@role="button" and '
            'contains('
            'translate(normalize-space(.),'
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            '"abcdefghijklmnopqrstuvwxyz"),'
            '"reactivate"'
            ')]'
        ),
    ]

    buttons = []

    for selector in selectors:

        try:
            buttons.extend(
                find_elements(root, selector)
            )
        except Exception:
            continue

    result = []

    for button in unique_elements(buttons):

        try:

            if button.is_displayed() and button.is_enabled():
                result.append(button)

        except Exception:
            continue

    return result


# ============================================================
# 找项目卡片
# ============================================================

def find_card_container_from_child(sb, child):

    try:

        return sb.driver.execute_script(
            """
            const start = arguments[0];

            let node = start;

            for (
                let i = 0;
                node && i < 12;
                i += 1,
                node = node.parentElement
            ) {

                const text =
                    (node.innerText || "").trim();

                const cls =
                    (node.className || "")
                    .toString()
                    .toLowerCase();

                const looksLikeCard =
                    /card|project|service|server|item|row/.test(cls);

                const hasActions =
                    /gérer|modifier|supprimer|renew|reactivate/i
                    .test(text);

                if (
                    node !== start &&
                    text.length > 20 &&
                    (
                        looksLikeCard ||
                        hasActions
                    )
                ) {
                    return node;
                }
            }

            return (
                start.parentElement ||
                start
            );
            """,
            child,
        )

    except Exception:
        return child


def find_project_cards(sb):

    cards = []

    # --------------------------------------------------------
    # 第一层：常见 card class
    # --------------------------------------------------------

    candidate_selectors = [
        ".projects-card",
        '[class*="projects-card"]',
        '[class*="project"][class*="card"]',
        '[class*="Project"][class*="Card"]',
        '[class*="service"][class*="card"]',
        '[class*="server"][class*="card"]',
        "article",
    ]

    for selector in candidate_selectors:

        try:

            elements = sb.driver.find_elements(
                By.CSS_SELECTOR,
                selector,
            )

            for card in elements:

                text = element_text(card)

                if len(text) < 5:
                    continue

                # 项目卡片特征
                if re.search(
                    r"gérer|modifier|supprimer|"
                    r"renew|reactivate|"
                    r"expires|expiry|expire|valid|"
                    r"续期|过期|到期",
                    text,
                    re.I,
                ):

                    cards.append(card)

        except Exception:
            continue

    cards = unique_elements(cards)

    if cards:
        return cards


    # --------------------------------------------------------
    # 第二层：直接从 Gérer / Modifier / Supprimer 找父容器
    # --------------------------------------------------------

    action_xpath = (
        '//*[self::button or self::a or '
        '@role="button" or self::div]'
        '['
        'contains('
        'translate(normalize-space(.),'
        '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
        '"abcdefghijklmnopqrstuvwxyz"),'
        '"gérer"'
        ')'
        'or '
        'contains('
        'translate(normalize-space(.),'
        '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
        '"abcdefghijklmnopqrstuvwxyz"),'
        '"modifier"'
        ')'
        'or '
        'contains('
        'translate(normalize-space(.),'
        '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
        '"abcdefghijklmnopqrstuvwxyz"),'
        '"supprimer"'
        ')'
        ']'
    )

    try:

        action_elements = sb.driver.find_elements(
            By.XPATH,
            action_xpath,
        )

        for element in action_elements:

            try:

                if not element.is_displayed():
                    continue

                card = find_card_container_from_child(
                    sb,
                    element,
                )

                if card:
                    cards.append(card)

            except Exception:
                continue

    except Exception:
        pass


    # --------------------------------------------------------
    # 第三层：Renew 按钮
    # --------------------------------------------------------

    for button in find_renew_buttons(sb.driver):

        try:

            card = find_card_container_from_child(
                sb,
                button,
            )

            if card:
                cards.append(card)

        except Exception:
            continue


    cards = unique_elements(cards)

    if cards:
        return dedupe_project_cards(cards)


    # --------------------------------------------------------
    # 第四层：当前页面的服务项目结构
    #
    # 根据你的日志：
    #
    # Mes Services
    # Mon VPS
    # Bot
    # python generic
    # Gérer
    # Modifier
    # Supprimer
    #
    # 因此尝试寻找包含这些文字的父元素。
    # --------------------------------------------------------

    try:

        service_xpath = (
            '//*[contains('
            'translate(normalize-space(.),'
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            '"abcdefghijklmnopqrstuvwxyz"),'
            '"gérer"'
            ')]'
        )

        services = sb.driver.find_elements(
            By.XPATH,
            service_xpath,
        )

        for service in services:

            try:

                if not service.is_displayed():
                    continue

                text = element_text(service)

                if len(text) < 10:
                    continue

                card = find_card_container_from_child(
                    sb,
                    service,
                )

                if card:
                    cards.append(card)

            except Exception:
                continue

    except Exception:
        pass


    cards = unique_elements(cards)

    return dedupe_project_cards(cards)


def dedupe_project_cards(cards):

    cards = unique_elements(cards)

    if not cards:
        return []

    # 按文本签名去重
    result = []
    seen = set()

    for card in cards:

        try:
            text = element_text(card)
        except Exception:
            continue

        if len(text) < 5:
            continue

        normalized = re.sub(
            r"\s+",
            " ",
            text.lower(),
        ).strip()

        # 避免把整个页面 body 当成卡片
        if len(normalized) > 3000:
            continue

        signature = normalized[:500]

        if signature in seen:
            continue

        seen.add(signature)
        result.append(card)

    return result


# ============================================================
# 续期提示
# ============================================================

def get_renewal_available_note(card):

    text = element_text(card)

    patterns = [
        r"Renewal\s+will\s+be\s+available[^\n]*",
        r"可续期[^\n]*",
        r"续期[^\n]*前[^\n]*",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I,
        )

        if match:
            return match.group(0).strip()

    return ""


def get_renew_note(card):

    selectors = [
        ".projects-renew-note",
        '[class*="renew-note"]',
        '[class*="note"]',
        '[class*="tip"]',
    ]

    for selector in selectors:

        try:

            elements = card.find_elements(
                By.CSS_SELECTOR,
                selector,
            )

            for elem in elements:

                text = element_text(elem)

                if text:
                    return text

        except Exception:
            continue

    return "未到续期时间"


def get_action_button_label(button):

    text = element_text(button)

    for attr in (
        "aria-label",
        "title",
    ):

        try:
            value = (
                button.get_attribute(attr)
                or ""
            ).strip()
        except Exception:
            value = ""

        if value:
            text = f"{text} {value}"

    lowered = text.lower()

    if (
        "reactivate" in lowered
        or "重新激活" in text
        or "恢复" in text
    ):
        return "Reactivate"

    return "Renew"


# ============================================================
# 卡片索引
# ============================================================

def get_card_by_index(sb, idx):

    cards = find_project_cards(sb)

    if idx <= len(cards):
        return cards[idx - 1]

    return None


# ============================================================
# 续期结果
# ============================================================

def wait_for_renew_result(
    sb,
    idx,
    timeout=30,
):

    start_time = time.time()

    while time.time() - start_time < timeout:

        try:

            # 成功弹窗
            success_modals = sb.driver.find_elements(
                By.XPATH,
                (
                    '//div[contains(@class,"modal") '
                    'and contains('
                    'translate(.,'
                    '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
                    '"abcdefghijklmnopqrstuvwxyz"),'
                    '"successfully"'
                    ')]'
                ),
            )

            for modal in success_modals:

                try:

                    if modal.is_displayed():

                        card = get_card_by_index(
                            sb,
                            idx,
                        )

                        expiry = (
                            get_project_expiry(card)
                            if card
                            else "未知"
                        )

                        return (
                            True,
                            expiry,
                            "success modal",
                        )

                except Exception:
                    pass


            # 页面状态变化
            card = get_card_by_index(
                sb,
                idx,
            )

            if card:

                renewal_note = (
                    get_renewal_available_note(
                        card
                    )
                )

                renew_buttons = (
                    find_renew_buttons(card)
                )

                if (
                    renewal_note
                    and not renew_buttons
                ):

                    return (
                        True,
                        get_project_expiry(card),
                        renewal_note,
                    )

        except Exception as e:

            print(
                f"检查续期结果时暂时失败: {e}"
            )

        sb.sleep(1)


    card = get_card_by_index(
        sb,
        idx,
    )

    note = (
        get_renewal_available_note(card)
        if card
        else ""
    )

    expiry = (
        get_project_expiry(card)
        if card
        else "未知"
    )

    return (
        False,
        expiry,
        note,
    )


# ============================================================
# 人机验证
# ============================================================

def click_captcha_checkbox(
    sb,
    label="验证码",
    timeout=10,
):

    selectors = [

        'div.auth-captcha-inner[role="checkbox"]',

        (
            '//div[contains(., "Anti-bot confirmation")]'
            '//*[@role="checkbox"]'
        ),

        (
            '//div[contains(., "I am not a robot")]'
            '//*[@role="checkbox"]'
        ),

        (
            '//div[contains(@class, "modal") '
            'and contains(., "Secured by ACLClouds")]'
            '//*[@role="checkbox"]'
        ),
    ]

    last_error = None

    clicked = False
    used_selector = None

    for candidate in selectors:

        try:

            sb.wait_for_element_visible(
                candidate,
                timeout=timeout,
            )

            scroll_to_selector(
                sb,
                candidate,
            )

            sb.uc_click(candidate)

            sb.sleep(1)

            used_selector = candidate
            clicked = True

            break

        except Exception as e:
            last_error = e

    if not clicked:

        print(
            f"{label} 点击复选框失败: "
            f"{last_error}"
        )

        return False

    # 等验证码加载
    sb.sleep(5)

    captcha_ok = handle_captcha_challenge(
        sb,
        label,
        timeout=20,
    )

    if not captcha_ok:

        print(
            f"{label} 验证流程未完成"
        )

        return False

    try:

        checkbox = sb.driver.find_element(
            By.CSS_SELECTOR,
            'div.auth-captcha-inner[role="checkbox"]',
        )

        checked = checkbox.get_attribute(
            "aria-checked"
        )

        if checked == "true":

            print(
                f"{label} 验证复选框已勾选，"
                f"验证码流程已完成"
            )

            print(f"{label} 验证通过")

            return True

        print(
            f"{label} 验证未完成，"
            f"当前状态: {checked}"
        )

        return False

    except Exception:

        # 有些情况下验证码完成后 DOM 会被重建
        # 只要挑战消失，也认为完成
        try:

            if not has_captcha_challenge(sb):

                print(
                    f"{label} 验证挑战已消失，"
                    f"认为验证完成"
                )

                return True

        except Exception:
            pass

        return False


def has_captcha_challenge(sb):

    selectors = [
        ".auth-captcha-challenge",
        ".auth-capcha-challenge",
    ]

    for selector in selectors:

        try:

            elements = sb.driver.find_elements(
                By.CSS_SELECTOR,
                selector,
            )

            for element in elements:

                if element.is_displayed():
                    return True

        except Exception:
            continue

    return False


def handle_captcha_challenge(
    sb,
    label="验证码",
    timeout=20,
):

    start_time = time.time()

    challenge = None

    challenge_selectors = [
        ".auth-captcha-challenge",
        ".auth-capcha-challenge",
        (
            '//*[contains(@class, "captcha") '
            'and contains(@class, "challenge")]'
        ),
        (
            '//*[contains(@aria-label, "Click on ") '
            'or contains(@aria-label, "Select ") '
            'or contains(@class, "challenge")]'
        ),
    ]

    def get_challenge():

        for selector in challenge_selectors:

            try:

                if selector.startswith("/"):

                    elements = sb.driver.find_elements(
                        By.XPATH,
                        selector,
                    )

                    for elem in elements:

                        if elem.is_displayed():
                            return elem

                else:

                    elements = sb.driver.find_elements(
                        By.CSS_SELECTOR,
                        selector,
                    )

                    for elem in elements:

                        if elem.is_displayed():
                            return elem

            except Exception:
                continue

        return None


    # 等待挑战
    while time.time() - start_time < timeout:

        challenge = get_challenge()

        if challenge:

            print(
                f"{label} 检测到图形验证码挑战"
            )

            break

        try:

            checkbox = sb.driver.find_element(
                By.CSS_SELECTOR,
                'div.auth-captcha-inner[role="checkbox"]',
            )

            if (
                checkbox.get_attribute(
                    "aria-checked"
                )
                == "true"
            ):

                print(
                    f"{label} 验证复选框已勾选，"
                    f"验证码流程已完成"
                )

                return True

        except Exception:
            pass

        sb.sleep(0.3)


    if not challenge:

        print(
            f"{label} 等待验证码挑战加载超时"
        )

        return False


    # --------------------------------------------------------
    # 获取目标
    # --------------------------------------------------------

    target = ""

    try:

        prompt = challenge.find_element(
            By.CSS_SELECTOR,
            ".auth-captcha-prompt strong",
        )

        target = prompt.text.strip()

    except Exception:
        pass


    if not target:

        try:

            prompt = challenge.find_element(
                By.CSS_SELECTOR,
                ".auth-capcha-prompt strong",
            )

            target = prompt.text.strip()

        except Exception:
            pass


    if not target:

        try:

            aria_label = (
                challenge.get_attribute(
                    "aria-label"
                )
                or ""
            )

            if "Click on " in aria_label:

                target = (
                    aria_label
                    .split("Click on ")[-1]
                    .strip()
                )

        except Exception:
            pass


    print(
        f"{label} 目标文本: "
        f"{target or '未识别'}"
    )


    # --------------------------------------------------------
    # 获取候选
    # --------------------------------------------------------

    def get_options(challenge_elem):

        selectors = [
            ".auth-captcha-option",
            ".auth-capcha-option",
        ]

        for selector in selectors:

            try:

                elements = challenge_elem.find_elements(
                    By.CSS_SELECTOR,
                    selector,
                )

                visible = []

                for elem in elements:

                    try:

                        if (
                            elem.is_displayed()
                            and elem.is_enabled()
                        ):
                            visible.append(elem)

                    except Exception:
                        pass

                if visible:
                    return visible

            except Exception:
                continue


        # XPath 兜底
        try:

            elements = challenge_elem.find_elements(
                By.XPATH,
                ".//button | .//a | .//*[@role='button']",
            )

            return [
                elem
                for elem in elements
                if elem.is_displayed()
                and elem.is_enabled()
            ]

        except Exception:
            return []


    # --------------------------------------------------------
    # 点击验证码
    # --------------------------------------------------------

    attempts = 0
    max_attempts = 8

    while attempts < max_attempts:

        challenge = get_challenge()

        if not challenge:

            return True


        options = get_options(
            challenge
        )

        if not options:

            print(
                f"{label} 当前挑战没有可点击选项，"
                f"重试中..."
            )

            attempts += 1

            sb.sleep(0.8)

            continue


        # 当前目标
        current_target = ""

        try:

            prompt = challenge.find_element(
                By.CSS_SELECTOR,
                ".auth-captcha-prompt strong",
            )

            current_target = prompt.text.strip()

        except Exception:
            pass


        if not current_target:

            try:

                aria_label = (
                    challenge.get_attribute(
                        "aria-label"
                    )
                    or ""
                )

                if "Click on " in aria_label:

                    current_target = (
                        aria_label
                        .split("Click on ")[-1]
                        .strip()
                    )

            except Exception:
                pass


        candidate = None

        # ----------------------------------------------------
        # 尝试寻找文字 / alt / aria-label 匹配
        # ----------------------------------------------------

        wanted = (
            current_target
            or target
        )

        if wanted:

            for opt in options:

                opt_text = ""

                try:
                    opt_text = (
                        opt.text
                        or ""
                    ).strip()
                except Exception:
                    pass

                if not opt_text:

                    try:

                        img = opt.find_element(
                            By.TAG_NAME,
                            "img",
                        )

                        opt_text = (
                            img.get_attribute(
                                "alt"
                            )
                            or ""
                        ).strip()

                    except Exception:
                        pass

                if not opt_text:

                    try:

                        opt_text = (
                            opt.get_attribute(
                                "aria-label"
                            )
                            or ""
                        ).strip()

                    except Exception:
                        pass

                if (
                    wanted.lower()
                    in opt_text.lower()
                ):

                    candidate = opt
                    break


        # ----------------------------------------------------
        # 如果无法识别，使用第一个候选
        # ----------------------------------------------------

        if candidate is None:

            candidate = options[0]


        print(
            f"{label} 点击候选选项 "
            f"#{attempts + 1} ..."
        )

        clicked = safe_click_element(
            sb,
            candidate,
            f"{label} 选项候选",
        )

        if not clicked:

            attempts += 1

            sb.sleep(0.8)

            continue


        sb.sleep(4.5)


        # ----------------------------------------------------
        # 检查 checkbox
        # ----------------------------------------------------

        try:

            checkbox = sb.driver.find_element(
                By.CSS_SELECTOR,
                'div.auth-captcha-inner[role="checkbox"]',
            )

            if (
                checkbox.get_attribute(
                    "aria-checked"
                )
                == "true"
            ):

                print(
                    f"{label} 验证复选框已勾选，"
                    f"验证码流程已完成"
                )

                return True

        except Exception:
            pass


        # challenge 消失
        if not get_challenge():

            print(
                f"{label} 挑战已消失，"
                f"验证完成"
            )

            return True


        attempts += 1


    print(
        f"{label} 多次尝试后仍未完成验证码"
    )

    return False


# ============================================================
# 登录
# ============================================================

def js_set_input_value(
    sb,
    selector,
    value,
):

    return sb.execute_script(
        """
        const el =
            document.querySelector(arguments[0]);

        if (!el) {
            return false;
        }

        el.focus();

        el.value =
            arguments[1];

        el.dispatchEvent(
            new Event(
                "input",
                { bubbles: true }
            )
        );

        el.dispatchEvent(
            new Event(
                "change",
                { bubbles: true }
            )
        );

        el.dispatchEvent(
            new Event(
                "blur",
                { bubbles: true }
            )
        );

        return true;
        """,
        selector,
        value,
    )


def fill_input(
    sb,
    selector,
    value,
    label,
    timeout=15,
):

    sb.wait_for_element_visible(
        selector,
        timeout=timeout,
    )

    scroll_to_selector(
        sb,
        selector,
    )

    sb.click(selector)

    sb.clear(selector)

    sb.type(
        selector,
        value,
    )

    entered_value = sb.get_value(
        selector
    )

    if label == "密码":

        print(
            f"{label}输入框当前值长度: "
            f"{len(entered_value)}"
        )

    else:

        print(
            f"{label}输入框当前值: "
            f"'{entered_value}'"
        )


    if entered_value != value:

        print(
            f"{label}输入未生效，"
            f"使用 JavaScript 强制赋值"
        )

        js_set_input_value(
            sb,
            selector,
            value,
        )

        entered_value = sb.get_value(
            selector
        )


    return entered_value == value


def login(
    sb,
    email,
    password,
):

    print("开始登录流程...")


    # --------------------------------------------------------
    # 邮箱
    # --------------------------------------------------------

    if not fill_input(
        sb,
        "#username",
        email,
        "邮箱",
    ):

        print(
            "⚠️ 邮箱仍未能正确填入"
        )


    # --------------------------------------------------------
    # 密码
    # --------------------------------------------------------

    if not fill_input(
        sb,
        "#password",
        password,
        "密码",
    ):

        print(
            "⚠️ 密码仍未能正确填入"
        )


    # --------------------------------------------------------
    # 验证码
    # --------------------------------------------------------

    captcha_ok = click_captcha_checkbox(
        sb,
        "登录验证码",
    )

    if not captcha_ok:

        print(
            "⚠️ 登录验证码未完成，"
            "暂不点击登录按钮"
        )

        return False


    sb.sleep(1)


    # --------------------------------------------------------
    # 登录
    # --------------------------------------------------------

    login_page_url = sb.get_current_url()

    clicked = False

    selectors = [
        "button[type='submit']",
        "div.auth-submit-btn",
        "//button[contains(text(), 'Sign in')]",
        "//div[contains(text(), 'Sign in')]",
    ]

    for selector in selectors:

        try:

            sb.wait_for_element_visible(
                selector,
                timeout=5,
            )

            scroll_to_selector(
                sb,
                selector,
            )

            sb.click(selector)

            clicked = True

            print(
                f"点击 Sign in 使用: "
                f"{selector}"
            )

            break

        except Exception as e:

            print(
                f"选择器 {selector} 失败: {e}"
            )


    if not clicked:

        print(
            "所有登录按钮选择器失败，"
            "使用 JS 点击"
        )

        try:

            result = sb.execute_script(
                """
                const elements =
                    document.querySelectorAll(
                        "button, div, a"
                    );

                for (
                    const el of elements
                ) {

                    if (
                        el.textContent
                        .trim()
                        === "Sign in"
                    ) {

                        el.click();

                        return true;
                    }
                }

                return false;
                """
            )

            if result:
                clicked = True

        except Exception as e:

            print(
                f"JS 点击失败: {e}"
            )


    if not clicked:

        print(
            "❌ 没有成功点击 Sign in"
        )

        return False


    # --------------------------------------------------------
    # 等待登录结果
    # --------------------------------------------------------

    try:

        wait_for_url_change(
            sb,
            login_page_url,
            timeout=30,
        )

    except Exception as e:

        print(
            f"等待登录结果异常: {e}"
        )

        return False


    current_url = sb.get_current_url()
    current_title = sb.get_title()

    print(
        f"登录后 URL: {current_url}"
    )

    print(
        f"登录后页面标题: {current_title}"
    )


    # ========================================================
    # 重要修复
    #
    # 不再使用：
    #
    # sb.assert_title('Home | ACLClouds')
    #
    # 因为你当前站点实际是：
    #
    # Accueil | ACLClouds
    #
    # 登录是否成功应该看 URL，而不是语言相关的标题。
    # ========================================================

    if LOGIN_PATH not in current_url:

        print(
            "登录状态检查 -> URL: "
            f"{current_url}"
        )

        print(
            "登录状态检查 -> 标题: "
            f"{current_title}"
        )

        print(
            "✅ 登录成功！"
        )

        return True


    # --------------------------------------------------------
    # 如果还在登录页，提取错误
    # --------------------------------------------------------

    error_msg = ""

    error_selectors = [
        ".auth-error-text",
        ".alert-danger",
        ".error-message",
        '[role="alert"]',
    ]

    for selector in error_selectors:

        try:

            errors = sb.driver.find_elements(
                By.CSS_SELECTOR,
                selector,
            )

            for error in errors:

                text = element_text(error)

                if text:

                    error_msg = text
                    break

            if error_msg:
                break

        except Exception:
            continue


    print(
        f"❌ 登录失败，错误: "
        f"{error_msg or '未获取到错误信息'}"
    )

    return False


# ============================================================
# IP
# ============================================================

def get_current_ip(
    proxy_server="",
):

    proxies = None

    if proxy_server:

        proxies = {
            "http": proxy_server,
            "https": proxy_server,
        }

    response = requests.get(
        "https://api.ip.sb/ip",
        proxies=proxies,
        timeout=15,
    )

    response.raise_for_status()

    return response.text.strip()


# ============================================================
# Telegram 消息
# ============================================================

def mask_email(email):

    if not email or "@" not in email:
        return email or ""

    local, domain = email.split(
        "@",
        1,
    )

    if len(local) <= 2:

        masked_local = (
            local[0] + "****"
            if local
            else "****"
        )

    elif len(local) <= 4:

        masked_local = (
            f"{local[0]}****{local[-1]}"
        )

    else:

        masked_local = (
            f"{local[:2]}****{local[-2:]}"
        )

    return (
        f"{masked_local}@{domain}"
    )


def build_success_message(
    project_name,
    old_expiry,
    new_expiry,
):

    masked_email = mask_email(
        EMAIL
    )

    lines = [
        "🇫🇷 Aclclouds 续期通知",
        "",
        "✅ 续期成功",
        f"📦 项目: {project_name}",
        f"⏱️ 新过期时间: {new_expiry}",
        f"👤 登录账户: {masked_email}",
        f"⏱️ 运行时间: {beijing_time_str()}",
    ]

    return "\n".join(lines)


def build_not_yet_due_message(
    project_name,
    expiry,
):

    masked_email = mask_email(
        EMAIL
    )

    lines = [
        "🇫🇷 Aclclouds 续期通知",
        "",
        "⏳ 未到续期时间",
        f"📦 项目: {project_name}",
        f"⏱️ 当前过期时间: {expiry}",
        f"👤 登录账户: {masked_email}",
        f"⏱️ 运行时间: {beijing_time_str()}",
    ]

    return "\n".join(lines)


def build_unconfirmed_message(
    project_name,
    old_expiry,
    new_expiry,
    result_note,
):

    masked_email = mask_email(
        EMAIL
    )

    lines = [
        "🇫🇷 Aclclouds 续期通知",
        "",
        f"❌ 续期状态未确认: {project_name}",
        f"👤 登录账户: {masked_email}",
    ]

    if (
        old_expiry
        and old_expiry.lower()
        not in [
            "suspended",
            "paused",
            "暂停",
        ]
    ):

        lines.append(
            f"旧过期: {old_expiry}"
        )

    lines.extend(
        [
            f"当前过期: {new_expiry}",
            (
                "页面提示: "
                f"{result_note or '未发现成功提示'}"
            ),
        ]
    )

    return "\n".join(lines)


# ============================================================
# Renew 后的人机验证
# ============================================================

def has_renew_antibot_modal(sb):

    selectors = [
        '//div[contains(., "Anti-bot confirmation")]',
        '//div[contains(., "Confirm you are human")]',
        '//div[contains(., "I am not a robot")]',
    ]

    for selector in selectors:

        try:

            elements = sb.driver.find_elements(
                By.XPATH,
                selector,
            )

            for elem in elements:

                if elem.is_displayed():
                    return True

        except Exception:
            continue

    return False


def handle_renew_antibot(
    sb,
    project_name,
):

    selectors = [
        '//div[contains(., "Anti-bot confirmation")]',
        '//div[contains(., "Confirm you are human")]',
        '//div[contains(., "I am not a robot")]',
    ]

    for selector in selectors:

        try:

            sb.wait_for_element_visible(
                selector,
                timeout=5,
            )

            print(
                f"[{project_name}] "
                f"检测到续期人机验证窗口"
            )

            return click_captcha_checkbox(
                sb,
                "续期人机验证",
                timeout=5,
            )

        except Exception:
            continue

    print(
        f"[{project_name}] "
        f"未检测到续期人机验证窗口"
    )

    return False


# ============================================================
# 页面诊断
# ============================================================

def log_projects_page_diagnostics(sb):

    current_url = sb.get_current_url()
    title = sb.get_title()

    body_text = ""

    try:

        body_text = (
            sb.driver
            .find_element(
                By.TAG_NAME,
                "body",
            )
            .text
            .strip()
        )

    except Exception:
        pass

    print(
        f"项目页诊断 URL: "
        f"{current_url}"
    )

    print(
        f"项目页诊断标题: "
        f"{title}"
    )

    print(
        "项目页可见文本摘要: "
        f"{body_text[:2000]}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    IS_PROXY = (
        os.environ
        .get(
            "IS_PROXY",
            "false",
        )
        .lower()
        == "true"
    )

    PROXY_SERVER = (
        os.getenv("S5_PROXY")
        or os.getenv("PROXY_SERVER")
        or "socks5://127.0.0.1:1080"
    )


    # --------------------------------------------------------
    # SeleniumBase
    # --------------------------------------------------------

    sb_options = {
        "uc": True,
        "headless": False,
    }

    if IS_PROXY:

        sb_options["proxy"] = PROXY_SERVER

        print(
            f"🔗 挂载代理: "
            f"{PROXY_SERVER}"
        )

    else:

        print(
            "🍭 未使用代理，直连访问"
        )


    with SB(**sb_options) as sb:

        try:

            # ------------------------------------------------
            # IP
            # ------------------------------------------------

            try:

                ip = get_current_ip(
                    PROXY_SERVER
                    if IS_PROXY
                    else ""
                )

                print(
                    f"📍 当前出口IP: {ip}"
                )

            except Exception as e:

                print(
                    f"获取出口IP失败: {e}"
                )


            sb.set_window_size(
                1366,
                768,
            )


            # ------------------------------------------------
            # 打开首页
            # ------------------------------------------------

            if not is_login_page(sb):

                sb.open(BASE_URL)

                sb.wait_for_ready_state_complete()

                time.sleep(2)


            # ------------------------------------------------
            # 登录
            # ------------------------------------------------

            if is_login_page(sb):

                print(
                    "执行正常登录..."
                )

                if not EMAIL or not PASSWORD:

                    print(
                        "❌ 未配置 EMAIL 或 PASSWORD"
                    )

                    send_telegram(
                        "⚠️ 未配置 EMAIL 或 PASSWORD。"
                    )

                    return


                if not login(
                    sb,
                    EMAIL,
                    PASSWORD,
                ):

                    send_telegram(
                        "⚠️ ACLClouds 登录失败，"
                        "请检查运行日志。"
                    )

                    return


            elif is_logged_in(sb):

                print(
                    "✅ 当前已登录。"
                )

                print(
                    f"URL: {sb.get_current_url()}"
                )

                print(
                    f"标题: {sb.get_title()}"
                )

            else:

                print(
                    "❌ 未能确认登录状态。"
                )

                print(
                    f"URL: {sb.get_current_url()}"
                )

                print(
                    f"标题: {sb.get_title()}"
                )

                send_telegram(
                    "⚠️ 未能确认登录状态，"
                    "请检查账号密码配置。"
                )

                return


            # ------------------------------------------------
            # 进入项目页
            # ------------------------------------------------

            print(
                f"📍 准备进入项目页: "
                f"{PROJECTS_URL}"
            )

            sb.open(
                PROJECTS_URL
            )

            sb.wait_for_ready_state_complete()

            time.sleep(3)


            print(
                f"📍 当前项目页 URL: "
                f"{sb.get_current_url()}"
            )

            print(
                f"📄 当前项目页标题: "
                f"{sb.get_title()}"
            )


            # ------------------------------------------------
            # 定位项目
            # ------------------------------------------------

            cards = find_project_cards(sb)


            if not cards:

                print(
                    "❌ 未找到项目卡片。"
                )

                log_projects_page_diagnostics(
                    sb
                )

                send_telegram(
                    "⚠️ 未找到项目卡片，"
                    "请检查页面结构。"
                )

                return


            print(
                f"找到 {len(cards)} 个项目卡片。"
            )


            # ------------------------------------------------
            # 遍历项目
            # ------------------------------------------------

            for idx, card in enumerate(
                cards,
                1,
            ):

                try:

                    project_name = (
                        get_project_name(
                            card,
                            idx,
                        )
                    )

                    old_expiry = (
                        get_project_expiry(
                            card
                        )
                    )

                    print(
                        f"[{project_name}] "
                        f"当前过期: "
                        f"{old_expiry}"
                    )


                    # ------------------------------------------------
                    # 找 Renew
                    # ------------------------------------------------

                    renew_btns = (
                        find_renew_buttons(
                            card
                        )
                    )


                    if renew_btns:

                        renew_btn = (
                            renew_btns[0]
                        )

                        action_label = (
                            get_action_button_label(
                                renew_btn
                            )
                        )


                        clicked = (
                            safe_click_element(
                                sb,
                                renew_btn,
                                (
                                    f"[{project_name}] "
                                    f"{action_label}按钮"
                                ),
                            )
                        )


                        if not clicked:

                            print(
                                f"[{project_name}] "
                                f"点击 {action_label} 失败"
                            )

                            send_telegram(
                                f"🇫🇷 Aclclouds 续期通知\n\n"
                                f"❌ 项目 {project_name} "
                                f"点击续期按钮失败"
                            )

                            continue


                        print(
                            f"[{project_name}] "
                            f"点击 {action_label}..."
                        )


                        # ------------------------------------------------
                        # Renew 后验证码
                        # ------------------------------------------------

                        if has_renew_antibot_modal(
                            sb
                        ):

                            handle_renew_antibot(
                                sb,
                                project_name,
                            )


                        # ------------------------------------------------
                        # 等待结果
                        # ------------------------------------------------

                        (
                            success,
                            new_expiry,
                            result_note,
                        ) = wait_for_renew_result(
                            sb,
                            idx,
                            timeout=30,
                        )


                        if success:

                            print(
                                f"续期成功！"
                                f"状态: {result_note}，"
                                f"新过期: {new_expiry}"
                            )

                            send_telegram(
                                build_success_message(
                                    project_name,
                                    old_expiry,
                                    new_expiry,
                                )
                            )

                        else:

                            print(
                                f"[{project_name}] "
                                f"续期状态未确认"
                            )

                            send_telegram(
                                build_unconfirmed_message(
                                    project_name,
                                    old_expiry,
                                    new_expiry,
                                    result_note,
                                )
                            )


                    else:

                        # ------------------------------------------------
                        # 没有 Renew
                        # ------------------------------------------------

                        note = get_renew_note(
                            card
                        )

                        print(
                            f"无 Renew 按钮，"
                            f"提示: {note}"
                        )

                        send_telegram(
                            build_not_yet_due_message(
                                project_name,
                                old_expiry,
                            )
                        )


                except Exception as e:

                    print(
                        f"处理卡片 {idx} 出错: {e}"
                    )

                    send_telegram(
                        "🇫🇷 Aclclouds 续期通知\n\n"
                        f"⚠️ 处理项目 #{idx} 出错:\n"
                        f"{str(e)}"
                    )


            print(
                "所有项目处理完成。"
            )


        except Exception as e:

            print(
                f"❌ 程序运行异常: {e}"
            )

            send_telegram(
                "🇫🇷 Aclclouds 续期通知\n\n"
                f"❌ 程序运行异常:\n{str(e)}"
            )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    main()
