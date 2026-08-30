#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import requests

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from seleniumbase import SB

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    WebDriverException,
    StaleElementReferenceException,
)

from selenium.webdriver.common.by import By


# ============================================================
# 配置
# ============================================================

EMAIL = os.getenv("EMAIL") or ""
PASSWORD = os.getenv("PASSWORD") or ""

TG_CHAT_ID = os.getenv("TG_CHAT_ID") or ""
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN") or ""

LOGIN_PATH = "/auth/login"

BASE_URL = "https://dash.aclclouds.com/"
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

    url = (
        f"https://api.telegram.org/"
        f"bot{TG_BOT_TOKEN}/sendMessage"
    )

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
            print(
                f"Telegram sent: "
                f"{message[:120]}..."
            )
        else:
            print(
                f"Telegram 返回错误: "
                f"{response.status_code} "
                f"{response.text[:300]}"
            )

    except Exception as e:
        print(
            f"Failed to send Telegram: {e}"
        )


# ============================================================
# URL / 登录状态
# ============================================================

def is_login_page(sb):
    try:
        return LOGIN_PATH.lower() in (
            sb.get_current_url() or ""
        ).lower()
    except Exception:
        return False


def is_logged_in_by_url(sb):
    try:
        current_url = (
            sb.get_current_url() or ""
        ).lower()

        if not current_url:
            return False

        if LOGIN_PATH.lower() in current_url:
            return False

        if (
            "dash.aclclouds.com" in current_url
            and (
                "/dashboard" in current_url
                or "/en/" in current_url
                or "/fr/" in current_url
            )
        ):
            return True

    except Exception:
        pass

    return False


def has_login_form(sb):
    selectors = [
        "#username",
        "#password",
        "input[name='username']",
        "input[name='email']",
        "input[type='password']",
    ]

    found_username = False
    found_password = False

    for selector in selectors:

        try:
            elements = sb.driver.find_elements(
                By.CSS_SELECTOR,
                selector,
            )

            for element in elements:

                try:
                    if not element.is_displayed():
                        continue
                except Exception:
                    continue

                if (
                    selector == "#username"
                    or "username" in selector
                    or "email" in selector
                ):
                    found_username = True

                if (
                    selector == "#password"
                    or "password" in selector
                ):
                    found_password = True

        except Exception:
            continue

    return found_username and found_password


def has_dashboard_content(sb):
    selectors = [
        "a[href*='/dashboard']",
        "a[href*='/projects']",
        "[class*='project']",
        "[class*='service']",
        "[class*='dashboard']",
    ]

    for selector in selectors:

        try:

            elements = sb.driver.find_elements(
                By.CSS_SELECTOR,
                selector,
            )

            for element in elements:

                try:
                    if element.is_displayed():
                        return True
                except Exception:
                    continue

        except Exception:
            continue

    return False


def detect_logged_in_state(sb):
    """
    登录成功判断。

    第一优先：
        URL 已经离开 /auth/login

    第二优先：
        登录表单已经消失 + 页面存在 dashboard 内容

    注意：
        不检查页面 title。
        因为站点可能是：
        Home | ACLClouds
        或：
        Accueil | ACLClouds
    """

    if is_logged_in_by_url(sb):
        return True

    try:
        login_form = has_login_form(sb)
    except Exception:
        login_form = True

    if not login_form:

        try:
            if has_dashboard_content(sb):
                return True
        except Exception:
            pass

        # 登录表单消失本身已经是比较强的信号
        return True

    return False


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
        print(
            f"{label} 元素已失效，需要重新定位"
        )
        return False

    except Exception as e:
        print(
            f"{label} 点击失败: {e}"
        )
        return False


def element_text(element):
    try:
        return (
            element.text or ""
        ).strip()
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

    if (
        selector.startswith("/")
        or selector.startswith(".//")
    ):
        by = By.XPATH
    else:
        by = By.CSS_SELECTOR

    try:
        return root.find_elements(
            by,
            selector,
        )
    except Exception:
        return []


# ============================================================
# 日期
# ============================================================

def extract_date_like(text):

    if not text:
        return ""

    patterns = [

        # 2026-08-30
        (
            r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"
            r"(?:\s+\d{1,2}:\d{2}"
            r"(?::\d{2})?)?"
        ),

        # 30/08/2026
        (
            r"\d{1,2}[-/]\d{1,2}[-/]\d{4}"
            r"(?:\s+\d{1,2}:\d{2}"
            r"(?::\d{2})?)?"
        ),

        # 2026.08.30
        (
            r"\d{4}\.\d{1,2}\.\d{1,2}"
            r"(?:\s+\d{1,2}:\d{2}"
            r"(?::\d{2})?)?"
        ),
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
        )

        if match:
            return match.group(0)

    return ""


# ============================================================
# 剩余时间
# ============================================================

def extract_duration_like(text):

    if not text:
        return ""

    text = (
        text.replace("\xa0", " ")
        .replace("\u202f", " ")
    )

    # --------------------------------------------------------
    # 例如：
    # 3j 11h
    # 3j
    # 11h
    # 3d 11h
    # 3 days 11 hours
    # 3 days
    # 11 hours
    # --------------------------------------------------------

    duration_patterns = [

        # 法语 / 英语短格式
        (
            r"\b"
            r"\d+\s*(?:j|d)"
            r"(?:\s+\d+\s*(?:h|hr|hrs))?"
            r"\b"
        ),

        (
            r"\b"
            r"\d+\s*(?:h|hr|hrs)"
            r"(?:\s+\d+\s*(?:m|min|mins))?"
            r"\b"
        ),

        # 英文
        (
            r"\b"
            r"\d+\s+"
            r"(?:days|day)"
            r"(?:\s+\d+\s+"
            r"(?:hours|hour))?"
            r"\b"
        ),

        (
            r"\b"
            r"\d+\s+"
            r"(?:hours|hour)"
            r"(?:\s+\d+\s+"
            r"(?:minutes|minute))?"
            r"\b"
        ),

        # 中文
        (
            r"\d+\s*天"
            r"(?:\s*\d+\s*小时)?"
        ),

        (
            r"\d+\s*小时"
            r"(?:\s*\d+\s*分钟)?"
        ),
    ]

    for pattern in duration_patterns:

        match = re.search(
            pattern,
            text,
            re.I,
        )

        if match:
            return (
                match.group(0)
                .strip()
            )

    # --------------------------------------------------------
    # 例如页面直接写：
    #
    # Expires in 3j 11h
    # Expire dans 3j 11h
    # Remaining: 3j 11h
    # --------------------------------------------------------

    keyword_pattern = re.search(
        r"(?:"
        r"expires?\s*(?:in)?"
        r"|expire(?:s|d)?\s*(?:dans)?"
        r"|remaining"
        r"|time\s+left"
        r"|剩余"
        r"|还有"
        r"|有效期"
        r")"
        r"\s*[:：]?\s*"
        r"("
        r"\d+\s*(?:j|d)"
        r"(?:\s+\d+\s*(?:h|hr|hrs))?"
        r"|"
        r"\d+\s*(?:h|hr|hrs)"
        r"(?:\s+\d+\s*(?:m|min|mins))?"
        r"|"
        r"\d+\s+days?"
        r"(?:\s+\d+\s+hours?)?"
        r"|"
        r"\d+\s+hours?"
        r"|"
        r"\d+\s*天"
        r"(?:\s*\d+\s*小时)?"
        r"|"
        r"\d+\s*小时"
        r"(?:\s*\d+\s*分钟)?"
        r")",
        text,
        re.I,
    )

    if keyword_pattern:
        return (
            keyword_pattern.group(1)
            .strip()
        )

    return ""


def normalize_duration(text):
    """
    将各种剩余时间格式统一成适合 Telegram 的显示。

    例如：
        3 days 11 hours -> 3d 11h
        3j 11h         -> 3j 11h
        11 hours       -> 11h
    """

    if not text:
        return ""

    text = (
        text.replace("\xa0", " ")
        .replace("\u202f", " ")
        .strip()
    )

    # 保留网站原始的法语 j / h
    if re.search(
        r"\d+\s*j\b",
        text,
        re.I,
    ):
        return re.sub(
            r"\s+",
            " ",
            text,
        )

    replacements = [
        (
            r"(\d+)\s*days?",
            r"\1d",
        ),
        (
            r"(\d+)\s*hours?",
            r"\1h",
        ),
        (
            r"(\d+)\s*hrs?",
            r"\1h",
        ),
        (
            r"(\d+)\s*minutes?",
            r"\1m",
        ),
        (
            r"(\d+)\s*mins?",
            r"\1m",
        ),
    ]

    result = text

    for pattern, replacement in replacements:

        result = re.sub(
            pattern,
            replacement,
            result,
            flags=re.I,
        )

    return re.sub(
        r"\s+",
        " ",
        result,
    ).strip()


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

                if any(
                    word in lowered
                    for word in (
                        "renew",
                        "reactivate",
                        "expiry",
                        "expires",
                    )
                ):
                    continue

                if extract_duration_like(text):
                    continue

                return text

        except Exception:
            continue

    lines = [
        line.strip()
        for line in element_text(card).splitlines()
        if line.strip()
    ]

    ignored = {
        "gérer",
        "gerer",
        "modifier",
        "supprimer",
        "renew",
        "reactivate",
        "renewal",
        "mes services",
        "my services",
        "services",
    }

    for line in lines:

        lowered = line.lower()

        if lowered in ignored:
            continue

        if len(line) > 80:
            continue

        if extract_date_like(line):
            continue

        if extract_duration_like(line):
            continue

        if re.search(
            r"expires|expiry|expire|valid|"
            r"renew|reactivate|"
            r"续期|过期|到期|剩余|"
            r"expires?\s+in",
            line,
            re.I,
        ):
            continue

        return line

    return f"项目 #{idx}"


# ============================================================
# 项目过期时间 / 剩余时间
# ============================================================

def get_project_expiry(card):

    if not card:
        return "未知"

    # --------------------------------------------------------
    # 第一优先：
    # 直接找 expiry / expire 相关 DOM
    # --------------------------------------------------------

    selectors = [

        ".projects-expiry-value",

        ".projects-service-cell--expiry strong",

        '[class*="expiry"] strong',

        '[class*="expiry"] [class*="value"]',

        '[class*="expires"] strong',

        '[class*="expire"] strong',

        '[class*="Expires"]',

        '[class*="expiry"]',

        '[class*="expire"]',

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

                date_text = extract_date_like(
                    text
                )

                if date_text:
                    return date_text

                duration_text = (
                    extract_duration_like(text)
                )

                if duration_text:
                    return normalize_duration(
                        duration_text
                    )

        except Exception:
            continue

    # --------------------------------------------------------
    # 第二优先：
    # 分析整张卡片文本
    # --------------------------------------------------------

    card_text = element_text(card)

    if not card_text:
        return "未知"

    # 先找带 expires / expiry 的行
    lines = [
        line.strip()
        for line in card_text.splitlines()
        if line.strip()
    ]

    for idx, line in enumerate(lines):

        lowered = line.lower()

        if re.search(
            r"expires?|expiry|expire|"
            r"expiration|"
            r"过期|到期|有效期|剩余",
            lowered,
            re.I,
        ):

            # 当前行
            date_text = extract_date_like(
                line
            )

            if date_text:
                return date_text

            duration = extract_duration_like(
                line
            )

            if duration:
                return normalize_duration(
                    duration
                )

            # 下一行
            if idx + 1 < len(lines):

                next_line = lines[
                    idx + 1
                ]

                date_text = (
                    extract_date_like(
                        next_line
                    )
                )

                if date_text:
                    return date_text

                duration = (
                    extract_duration_like(
                        next_line
                    )
                )

                if duration:
                    return normalize_duration(
                        duration
                    )

    # --------------------------------------------------------
    # 第三优先：
    # 整体搜索剩余时间
    # --------------------------------------------------------

    duration = extract_duration_like(
        card_text
    )

    if duration:
        return normalize_duration(
            duration
        )

    # --------------------------------------------------------
    # 第四优先：
    # 整体搜索日期
    # --------------------------------------------------------

    date_text = extract_date_like(
        card_text
    )

    if date_text:
        return date_text

    return "未知"


# ============================================================
# Renew 按钮
# ============================================================

def find_renew_buttons(root):

    selectors = [

        ".projects-renew-btn",

        'button[title*="renew" i]',

        'button[aria-label*="renew" i]',

        'button[aria-label*="reactivate" i]',

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
                find_elements(
                    root,
                    selector,
                )
            )

        except Exception:
            continue

    result = []

    for button in unique_elements(
        buttons
    ):

        try:

            if (
                button.is_displayed()
                and button.is_enabled()
            ):
                result.append(button)

        except Exception:
            continue

    return result


# ============================================================
# 找项目卡片
# ============================================================

def find_card_container_from_child(
    sb,
    child,
):

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
                    /gérer|gerer|modifier|supprimer|renew|reactivate/i
                    .test(text);

                const hasExpiry =
                    /expires|expiry|expire|expiration|remaining|\
                    过期|到期|剩余/i.test(text);

                if (
                    node !== start &&
                    text.length > 20 &&
                    (
                        looksLikeCard ||
                        hasActions ||
                        hasExpiry
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


def dedupe_project_cards(cards):

    cards = unique_elements(cards)

    if not cards:
        return []

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

        if len(normalized) > 3000:
            continue

        signature = normalized[:800]

        if signature in seen:
            continue

        seen.add(signature)
        result.append(card)

    return result


def find_project_cards(sb):

    cards = []

    # --------------------------------------------------------
    # 第一层：明确的项目卡片
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

                if re.search(
                    r"gérer|gerer|modifier|supprimer|"
                    r"renew|reactivate|"
                    r"expires|expiry|expire|"
                    r"expiration|remaining|"
                    r"续期|过期|到期|剩余",
                    text,
                    re.I,
                ):

                    cards.append(card)

        except Exception:
            continue

    cards = unique_elements(cards)

    if cards:
        return dedupe_project_cards(cards)

    # --------------------------------------------------------
    # 第二层：从 Gérer / Modifier / Supprimer 找父容器
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
        '"gerer"'
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

        action_elements = (
            sb.driver.find_elements(
                By.XPATH,
                action_xpath,
            )
        )

        for element in action_elements:

            try:

                if not element.is_displayed():
                    continue

                card = (
                    find_card_container_from_child(
                        sb,
                        element,
                    )
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

    for button in find_renew_buttons(
        sb.driver
    ):

        try:

            card = (
                find_card_container_from_child(
                    sb,
                    button,
                )
            )

            if card:
                cards.append(card)

        except Exception:
            continue

    cards = unique_elements(cards)

    if cards:
        return dedupe_project_cards(cards)

    # --------------------------------------------------------
    # 第四层：寻找包含 Gérer 的服务节点
    # --------------------------------------------------------

    try:

        service_xpath = (
            '//*[contains('
            'translate(normalize-space(.),'
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            '"abcdefghijklmnopqrstuvwxyz"),'
            '"gérer"'
            ') or contains('
            'translate(normalize-space(.),'
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            '"abcdefghijklmnopqrstuvwxyz"),'
            '"gerer"'
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

                card = (
                    find_card_container_from_child(
                        sb,
                        service,
                    )
                )

                if card:
                    cards.append(card)

            except Exception:
                continue

    except Exception:
        pass

    return dedupe_project_cards(cards)


# ============================================================
# 续期提示
# ============================================================

def get_renewal_available_note(card):

    if not card:
        return ""

    text = element_text(card)

    patterns = [

        r"Renewal\s+will\s+be\s+available[^\n]*",

        r"renewal[^\n]*available[^\n]*",

        r"renouvellement[^\n]*",

        r"renew[^\n]*available[^\n]*",

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
            return (
                match.group(0)
                .strip()
            )

    return ""


def get_renew_note(card):

    if not card:
        return "未到续期时间"

    selectors = [
        ".projects-renew-note",
        '[class*="renew-note"]',
        '[class*="renewal-note"]',
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

    # 从文本中判断
    text = element_text(card)

    if re.search(
        r"not\s+available|"
        r"not\s+yet|"
        r"available\s+in|"
        r"renouvellement|"
        r"pas\s+encore|"
        r"可续期|"
        r"未到续期",
        text,
        re.I,
    ):

        for line in text.splitlines():

            line = line.strip()

            if re.search(
                r"not\s+available|"
                r"not\s+yet|"
                r"available\s+in|"
                r"renouvellement|"
                r"pas\s+encore|"
                r"可续期|"
                r"未到续期",
                line,
                re.I,
            ):
                return line

    return "未到续期时间"


def get_action_button_label(button):

    text = element_text(button)

    for attr in (
        "aria-label",
        "title",
    ):

        try:

            value = (
                button.get_attribute(
                    attr
                )
                or ""
            ).strip()

        except Exception:
            value = ""

        if value:
            text = (
                f"{text} {value}"
            )

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

def page_has_success_message(sb):

    success_patterns = [
        "successfully",
        "success",
        "renewed successfully",
        "renewal successful",
        "renewal completed",
        "reactivated",
        "renewed",
        "succès",
        "renouvelé",
        "renouvellement effectué",
        "续期成功",
        "成功续期",
    ]

    try:

        body = (
            sb.driver
            .find_element(
                By.TAG_NAME,
                "body",
            )
            .text
            .strip()
            .lower()
        )

    except Exception:
        return False

    for pattern in success_patterns:

        if pattern.lower() in body:
            return True

    return False


def wait_for_renew_result(
    sb,
    idx,
    old_expiry="",
    timeout=30,
):

    start_time = time.time()

    last_expiry = old_expiry or "未知"

    while (
        time.time() - start_time
        < timeout
    ):

        try:

            # ------------------------------------------------
            # 成功弹窗
            # ------------------------------------------------

            success_modals = (
                sb.driver.find_elements(
                    By.XPATH,
                    (
                        '//div[contains(@class,"modal") '
                        'and ('
                        'contains('
                        'translate(.,'
                        '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
                        '"abcdefghijklmnopqrstuvwxyz"),'
                        '"successfully"'
                        ')'
                        'or contains('
                        'translate(.,'
                        '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
                        '"abcdefghijklmnopqrstuvwxyz"),'
                        '"renewed"'
                        ')'
                        'or contains('
                        'translate(.,'
                        '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
                        '"abcdefghijklmnopqrstuvwxyz"),'
                        '"success"'
                        ')'
                        ')]'
                    ),
                )
            )

            for modal in success_modals:

                try:

                    if modal.is_displayed():

                        card = (
                            get_card_by_index(
                                sb,
                                idx,
                            )
                        )

                        expiry = (
                            get_project_expiry(
                                card
                            )
                            if card
                            else last_expiry
                        )

                        if expiry != "未知":
                            last_expiry = expiry

                        return (
                            True,
                            last_expiry,
                            "续期成功",
                        )

                except Exception:
                    pass

            # ------------------------------------------------
            # 页面整体成功提示
            # ------------------------------------------------

            if page_has_success_message(sb):

                card = (
                    get_card_by_index(
                        sb,
                        idx,
                    )
                )

                expiry = (
                    get_project_expiry(
                        card
                    )
                    if card
                    else last_expiry
                )

                if expiry != "未知":
                    last_expiry = expiry

                return (
                    True,
                    last_expiry,
                    "续期成功",
                )

            # ------------------------------------------------
            # 卡片状态
            # ------------------------------------------------

            card = get_card_by_index(
                sb,
                idx,
            )

            if card:

                current_expiry = (
                    get_project_expiry(
                        card
                    )
                )

                if current_expiry != "未知":
                    last_expiry = (
                        current_expiry
                    )

                renewal_note = (
                    get_renewal_available_note(
                        card
                    )
                )

                renew_buttons = (
                    find_renew_buttons(
                        card
                    )
                )

                # 页面状态发生变化
                if (
                    current_expiry != "未知"
                    and old_expiry
                    and current_expiry
                    != old_expiry
                ):

                    return (
                        True,
                        current_expiry,
                        "续期成功，过期时间已更新",
                    )

                if (
                    renewal_note
                    and not renew_buttons
                ):

                    return (
                        True,
                        current_expiry,
                        renewal_note,
                    )

        except Exception as e:

            print(
                f"检查续期结果时暂时失败: "
                f"{e}"
            )

        sb.sleep(1)

    # --------------------------------------------------------
    # 最终重新读取卡片
    # --------------------------------------------------------

    card = get_card_by_index(
        sb,
        idx,
    )

    if card:

        expiry = get_project_expiry(
            card
        )

        if expiry != "未知":
            last_expiry = expiry

        note = (
            get_renewal_available_note(
                card
            )
        )

    else:

        note = ""

    return (
        False,
        last_expiry,
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
            '//div[contains(., "Confirm you are human")]'
            '//*[@role="checkbox"]'
        ),

        (
            '//div[contains(., "I am not a robot")]'
            '//*[@role="checkbox"]'
        ),

        (
            '//div[contains(., "Secured by ACLClouds")]'
            '//*[@role="checkbox"]'
        ),
    ]

    last_error = None

    clicked = False

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

        checked = (
            checkbox.get_attribute(
                "aria-checked"
            )
        )

        if checked == "true":

            print(
                f"{label} 验证复选框已勾选，"
                f"验证码流程已完成"
            )

            print(
                f"{label} 验证通过"
            )

            return True

    except Exception:
        pass

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

            elements = (
                sb.driver.find_elements(
                    By.CSS_SELECTOR,
                    selector,
                )
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

                    elements = (
                        sb.driver.find_elements(
                            By.XPATH,
                            selector,
                        )
                    )

                else:

                    elements = (
                        sb.driver.find_elements(
                            By.CSS_SELECTOR,
                            selector,
                        )
                    )

                for elem in elements:

                    if elem.is_displayed():
                        return elem

            except Exception:
                continue

        return None

    # --------------------------------------------------------
    # 等待挑战
    # --------------------------------------------------------

    challenge = None

    while (
        time.time() - start_time
        < timeout
    ):

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

    prompt_selectors = [
        ".auth-captcha-prompt strong",
        ".auth-capcha-prompt strong",
    ]

    for selector in prompt_selectors:

        try:

            prompt = challenge.find_element(
                By.CSS_SELECTOR,
                selector,
            )

            target = (
                prompt.text or ""
            ).strip()

            if target:
                break

        except Exception:
            continue

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
                    .split("Click on ", 1)[1]
                    .strip()
                )

            elif "Select " in aria_label:

                target = (
                    aria_label
                    .split("Select ", 1)[1]
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

    def get_options(
        challenge_elem
    ):

        selectors = [
            ".auth-captcha-option",
            ".auth-capcha-option",
        ]

        for selector in selectors:

            try:

                elements = (
                    challenge_elem.find_elements(
                        By.CSS_SELECTOR,
                        selector,
                    )
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

        try:

            elements = (
                challenge_elem.find_elements(
                    By.XPATH,
                    ".//button | "
                    ".//a | "
                    ".//*[@role='button']",
                )
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

        current_target = ""

        for selector in prompt_selectors:

            try:

                prompt = challenge.find_element(
                    By.CSS_SELECTOR,
                    selector,
                )

                current_target = (
                    prompt.text or ""
                ).strip()

                if current_target:
                    break

            except Exception:
                continue

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
                        .split("Click on ", 1)[1]
                        .strip()
                    )

                elif "Select " in aria_label:

                    current_target = (
                        aria_label
                        .split("Select ", 1)[1]
                        .strip()
                    )

            except Exception:
                pass

        wanted = (
            current_target
            or target
        )

        candidate = None

        # ----------------------------------------------------
        # 尝试文字 / alt / aria-label
        # ----------------------------------------------------

        if wanted:

            for opt in options:

                opt_text = ""

                try:
                    opt_text = (
                        opt.text or ""
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
        # 无法识别时使用第一个候选
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
# 输入框
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

        const setter =
            Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype,
                "value"
            );

        if (setter && setter.set) {
            setter.set.call(
                el,
                arguments[1]
            );
        } else {
            el.value = arguments[1];
        }

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

        entered_value = (
            sb.get_value(selector)
        )

    return entered_value == value


# ============================================================
# 登录错误
# ============================================================

def get_login_error(sb):

    selectors = [
        ".auth-error-text",
        ".alert-danger",
        ".error-message",
        '[role="alert"]',
        ".invalid-feedback",
    ]

    for selector in selectors:

        try:

            errors = (
                sb.driver.find_elements(
                    By.CSS_SELECTOR,
                    selector,
                )
            )

            for error in errors:

                try:
                    if not error.is_displayed():
                        continue
                except Exception:
                    pass

                text = element_text(error)

                if text:
                    return text

        except Exception:
            continue

    # 页面文本兜底
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

        lines = [
            line.strip()
            for line in body_text.splitlines()
            if line.strip()
        ]

        keywords = [
            "invalid",
            "incorrect",
            "wrong password",
            "authentication failed",
            "login failed",
            "identifiants",
            "mot de passe",
            "incorrect",
            "erreur",
        ]

        for line in lines:

            lowered = line.lower()

            if any(
                key in lowered
                for key in keywords
            ):

                if len(line) < 300:
                    return line

    except Exception:
        pass

    return ""


# ============================================================
# 登录
# ============================================================

def login(
    sb,
    email,
    password,
):

    print("开始登录流程...")

    # --------------------------------------------------------
    # 邮箱
    # --------------------------------------------------------

    email_selectors = [
        "#username",
        "input[name='username']",
        "input[name='email']",
        "input[type='email']",
    ]

    email_selector = None

    for selector in email_selectors:

        try:

            if sb.is_element_visible(
                selector
            ):

                email_selector = selector
                break

        except Exception:
            continue

    if not email_selector:

        print(
            "❌ 找不到邮箱输入框"
        )

        return False

    if not fill_input(
        sb,
        email_selector,
        email,
        "邮箱",
    ):

        print(
            "⚠️ 邮箱仍未能正确填入"
        )

    # --------------------------------------------------------
    # 密码
    # --------------------------------------------------------

    password_selectors = [
        "#password",
        "input[name='password']",
        "input[type='password']",
    ]

    password_selector = None

    for selector in password_selectors:

        try:

            if sb.is_element_visible(
                selector
            ):

                password_selector = selector
                break

        except Exception:
            continue

    if not password_selector:

        print(
            "❌ 找不到密码输入框"
        )

        return False

    if not fill_input(
        sb,
        password_selector,
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
    # 登录按钮
    # --------------------------------------------------------

    login_page_url = (
        sb.get_current_url()
    )

    clicked = False

    selectors = [

        "button[type='submit']",

        "div.auth-submit-btn",

        (
            "//button[contains("
            "translate(normalize-space(.),"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz'),"
            "'sign in')]"
        ),

        (
            "//button[contains("
            "translate(normalize-space(.),"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz'),"
            "'connexion')]"
        ),

        (
            "//button[contains("
            "translate(normalize-space(.),"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz'),"
            "'se connecter')]"
        ),

        (
            "//div[contains("
            "translate(normalize-space(.),"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz'),"
            "'sign in')]"
        ),
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
                f"选择器 {selector} 失败: "
                f"{e}"
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

                for (const el of elements) {

                    const text =
                        (el.textContent || "")
                        .trim()
                        .toLowerCase();

                    if (
                        text === "sign in" ||
                        text === "connexion" ||
                        text === "se connecter"
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
            "❌ 没有成功点击登录按钮"
        )

        return False

    # --------------------------------------------------------
    # 等待登录
    #
    # 这里不再强制要求 URL 一定变化。
    # --------------------------------------------------------

    print(
        "等待登录结果..."
    )

    start_time = time.time()

    login_success = False

    while (
        time.time() - start_time
        < 30
    ):

        current_url = (
            sb.get_current_url()
        )

        # 最可靠判断
        if (
            LOGIN_PATH.lower()
            not in current_url.lower()
        ):

            login_success = True
            break

        # URL 没变化时检查登录表单
        try:

            if not has_login_form(sb):

                sb.sleep(1)

                if not is_login_page(sb):

                    login_success = True
                    break

                if has_dashboard_content(sb):

                    login_success = True
                    break

        except Exception:
            pass

        # 如果出现明确登录错误
        error_msg = get_login_error(sb)

        if error_msg:

            print(
                f"❌ 检测到登录错误: "
                f"{error_msg}"
            )

            return False

        sb.sleep(0.5)

    current_url = sb.get_current_url()

    current_title = sb.get_title()

    print(
        f"登录后 URL: {current_url}"
    )

    print(
        f"登录后页面标题: {current_title}"
    )

    # --------------------------------------------------------
    # 最终登录成功判断
    # --------------------------------------------------------

    if (
        LOGIN_PATH.lower()
        not in current_url.lower()
    ):

        print(
            "✅ 登录成功！"
        )

        return True

    if detect_logged_in_state(sb):

        print(
            "✅ 登录成功！"
        )

        return True

    error_msg = get_login_error(sb)

    print(
        f"❌ 登录失败，错误: "
        f"{error_msg or '未获取到明确错误信息'}"
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


def build_login_success_message():

    masked_email = mask_email(
        EMAIL
    )

    return "\n".join(
        [
            "🇫🇷 Aclclouds 续期通知",
            "",
            "✅ 登录成功",
            f"👤 登录账户: {masked_email}",
            f"⏱️ 运行时间: {beijing_time_str()}",
        ]
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
        f"⏱️ 续期前: {old_expiry}",
        f"⏱️ 续期后: {new_expiry}",
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
        f"⚠️ 续期状态未确认",
        f"📦 项目: {project_name}",
        f"⏱️ 续期前: {old_expiry}",
        f"⏱️ 当前过期: {new_expiry}",
        f"👤 登录账户: {masked_email}",
        (
            "📄 页面提示: "
            f"{result_note or '未发现明确结果'}"
        ),
        f"⏱️ 运行时间: {beijing_time_str()}",
    ]

    return "\n".join(lines)


def build_login_failed_message():

    masked_email = mask_email(
        EMAIL
    )

    return "\n".join(
        [
            "🇫🇷 Aclclouds 续期通知",
            "",
            "❌ 登录失败",
            f"👤 登录账户: {masked_email}",
            f"⏱️ 运行时间: {beijing_time_str()}",
            "",
            "请检查账号密码或验证码状态。",
        ]
    )


# ============================================================
# Renew 后的人机验证
# ============================================================

def has_renew_antibot_modal(sb):

    selectors = [

        (
            '//div[contains('
            'translate(.,'
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            '"abcdefghijklmnopqrstuvwxyz"),'
            '"anti-bot confirmation"'
            ')]'
        ),

        (
            '//div[contains('
            'translate(.,'
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            '"abcdefghijklmnopqrstuvwxyz"),'
            '"confirm you are human"'
            ')]'
        ),

        (
            '//div[contains('
            'translate(.,'
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            '"abcdefghijklmnopqrstuvwxyz"),'
            '"i am not a robot"'
            ')]'
        ),

        (
            '//div[contains(., "Vérification")]'
        ),

        (
            '//div[contains(., "confirmation")]'
        ),
    ]

    for selector in selectors:

        try:

            elements = (
                sb.driver.find_elements(
                    By.XPATH,
                    selector,
                )
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

        (
            '//div[contains('
            'translate(.,'
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            '"abcdefghijklmnopqrstuvwxyz"),'
            '"anti-bot confirmation"'
            ')]'
        ),

        (
            '//div[contains('
            'translate(.,'
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            '"abcdefghijklmnopqrstuvwxyz"),'
            '"confirm you are human"'
            ')]'
        ),

        (
            '//div[contains('
            'translate(.,'
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            '"abcdefghijklmnopqrstuvwxyz"),'
            '"i am not a robot"'
            ')]'
        ),

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
        f"{body_text[:3000]}"
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

        sb_options["proxy"] = (
            PROXY_SERVER
        )

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

            print(
                "打开 ACLClouds..."
            )

            sb.open(BASE_URL)

            sb.wait_for_ready_state_complete()

            time.sleep(2)

            print(
                f"当前 URL: "
                f"{sb.get_current_url()}"
            )

            print(
                f"当前标题: "
                f"{sb.get_title()}"
            )

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
                        "⚠️ 未配置 "
                        "EMAIL 或 PASSWORD。"
                    )

                    return

                if not login(
                    sb,
                    EMAIL,
                    PASSWORD,
                ):

                    print(
                        "❌ ACLClouds 登录失败"
                    )

                    send_telegram(
                        build_login_failed_message()
                    )

                    return

            elif detect_logged_in_state(sb):

                print(
                    "✅ 当前已登录。"
                )

                print(
                    f"URL: "
                    f"{sb.get_current_url()}"
                )

                print(
                    f"标题: "
                    f"{sb.get_title()}"
                )

            else:

                # --------------------------------------------
                # 首页可能需要再进入项目页验证登录状态
                # --------------------------------------------

                print(
                    "当前页面无法直接确认登录状态，"
                    "尝试进入项目页验证..."
                )

                try:

                    sb.open(
                        PROJECTS_URL
                    )

                    sb.wait_for_ready_state_complete()

                    time.sleep(2)

                except Exception as e:

                    print(
                        f"进入项目页失败: {e}"
                    )

                if is_login_page(sb):

                    print(
                        "页面仍在登录页，"
                        "执行正常登录..."
                    )

                    if not EMAIL or not PASSWORD:

                        print(
                            "❌ 未配置 "
                            "EMAIL 或 PASSWORD"
                        )

                        send_telegram(
                            "⚠️ 未配置 "
                            "EMAIL 或 PASSWORD。"
                        )

                        return

                    if not login(
                        sb,
                        EMAIL,
                        PASSWORD,
                    ):

                        send_telegram(
                            build_login_failed_message()
                        )

                        return

                elif detect_logged_in_state(sb):

                    print(
                        "✅ 登录状态确认成功！"
                    )

                else:

                    print(
                        "❌ 未能确认登录状态。"
                    )

                    print(
                        f"URL: "
                        f"{sb.get_current_url()}"
                    )

                    print(
                        f"标题: "
                        f"{sb.get_title()}"
                    )

                    send_telegram(
                        "⚠️ 未能确认登录状态，"
                        "请检查账号密码配置。"
                    )

                    return

            # ------------------------------------------------
            # 再次确认
            # ------------------------------------------------

            print(
                "检查登录状态..."
            )

            if (
                is_login_page(sb)
                and not detect_logged_in_state(sb)
            ):

                print(
                    "❌ 当前仍处于登录页面"
                )

                send_telegram(
                    build_login_failed_message()
                )

                return

            print(
                "✅ 登录成功！"
            )

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
            # 如果项目页被重定向到登录页
            # ------------------------------------------------

            if is_login_page(sb):

                print(
                    "⚠️ 项目页被重定向到登录页，"
                    "登录状态失效。"
                )

                send_telegram(
                    "⚠️ ACLClouds 项目页需要重新登录。"
                )

                return

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

                        print(
                            f"[{project_name}] "
                            f"检测到 {action_label} 按钮"
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
                                "\n".join(
                                    [
                                        "🇫🇷 Aclclouds 续期通知",
                                        "",
                                        "❌ 点击续期按钮失败",
                                        f"📦 项目: {project_name}",
                                        f"⏱️ 当前过期时间: {old_expiry}",
                                        f"⏱️ 运行时间: {beijing_time_str()}",
                                    ]
                                )
                            )

                            continue

                        print(
                            f"[{project_name}] "
                            f"点击 {action_label}..."
                        )

                        sb.sleep(2)

                        # ------------------------------------------------
                        # Renew 后验证码
                        # ------------------------------------------------

                        if has_renew_antibot_modal(
                            sb
                        ):

                            captcha_result = (
                                handle_renew_antibot(
                                    sb,
                                    project_name,
                                )
                            )

                            if not captcha_result:

                                print(
                                    f"[{project_name}] "
                                    f"续期人机验证失败"
                                )

                                send_telegram(
                                    "\n".join(
                                        [
                                            "🇫🇷 Aclclouds 续期通知",
                                            "",
                                            "❌ 续期验证码失败",
                                            f"📦 项目: {project_name}",
                                            f"⏱️ 当前过期时间: {old_expiry}",
                                            f"⏱️ 运行时间: {beijing_time_str()}",
                                        ]
                                    )
                                )

                                continue

                        # ------------------------------------------------
                        # 等待续期结果
                        # ------------------------------------------------

                        (
                            success,
                            new_expiry,
                            result_note,
                        ) = wait_for_renew_result(
                            sb,
                            idx,
                            old_expiry=old_expiry,
                            timeout=30,
                        )

                        if success:

                            print(
                                f"[{project_name}] "
                                f"续期成功！"
                            )

                            print(
                                f"[{project_name}] "
                                f"续期前: "
                                f"{old_expiry}"
                            )

                            print(
                                f"[{project_name}] "
                                f"续期后: "
                                f"{new_expiry}"
                            )

                            print(
                                f"[{project_name}] "
                                f"状态: "
                                f"{result_note}"
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

                            print(
                                f"[{project_name}] "
                                f"当前过期: "
                                f"{new_expiry}"
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

                        note = (
                            get_renew_note(
                                card
                            )
                        )

                        # 再次读取一次，防止第一次 DOM
                        # 读取时没有加载完成
                        current_expiry = (
                            get_project_expiry(
                                card
                            )
                        )

                        if (
                            current_expiry
                            == "未知"
                            and old_expiry
                            != "未知"
                        ):
                            current_expiry = (
                                old_expiry
                            )

                        print(
                            f"[{project_name}] "
                            f"无 Renew 按钮，"
                            f"提示: {note}"
                        )

                        print(
                            f"[{project_name}] "
                            f"当前剩余/过期时间: "
                            f"{current_expiry}"
                        )

                        send_telegram(
                            build_not_yet_due_message(
                                project_name,
                                current_expiry,
                            )
                        )

                except Exception as e:

                    print(
                        f"处理卡片 {idx} 出错: "
                        f"{e}"
                    )

                    send_telegram(
                        "\n".join(
                            [
                                "🇫🇷 Aclclouds 续期通知",
                                "",
                                f"⚠️ 处理项目 #{idx} 出错",
                                f"错误: {str(e)}",
                                f"⏱️ 运行时间: {beijing_time_str()}",
                            ]
                        )
                    )

            print(
                "所有项目处理完成。"
            )

        except Exception as e:

            print(
                f"❌ 程序运行异常: {e}"
            )

            send_telegram(
                "\n".join(
                    [
                        "🇫🇷 Aclclouds 续期通知",
                        "",
                        "❌ 程序运行异常",
                        f"错误: {str(e)}",
                        f"⏱️ 运行时间: {beijing_time_str()}",
                    ]
                )
            )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    main()
