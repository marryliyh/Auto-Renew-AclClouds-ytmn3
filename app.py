#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ACLClouds 服务续期脚本（SeleniumBase）。

环境变量：
  EMAIL, PASSWORD                  ACLClouds 登录信息（必填）
  TG_BOT_TOKEN, TG_CHAT_ID         Telegram 通知（可选）
  PROXY                            例如 socks5://127.0.0.1:1080（可选）
  HEADLESS                         1 / true 时启用无头浏览器（可选）
  LOGIN_URL                        覆盖默认登录入口（可选）
  DRY_RUN                          1 / true 时只检测、不会点击续期（可选）

依赖：pip install seleniumbase requests
运行：python aclclouds_renew.py
"""

import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit

import requests
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from seleniumbase import SB

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None


EMAIL = os.getenv("EMAIL", "").strip()
PASSWORD = os.getenv("PASSWORD", "")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()
PROXY = (os.getenv("PROXY") or os.getenv("S5_PROXY") or os.getenv("PROXY_SERVER") or "").strip()
LOGIN_URL = os.getenv("LOGIN_URL", "https://dash.aclclouds.com/auth/login").strip()
HEADLESS = os.getenv("HEADLESS", "").strip().lower() in {"1", "true", "yes"}
DRY_RUN = os.getenv("DRY_RUN", "").strip().lower() in {"1", "true", "yes"}

PROJECTS_PATH = "/dashboard/projects"
LOGIN_PATHS = ("/auth/login", "/login", "/signin", "/sign-in")

ACTION_WORDS = (
    "renew", "renewal", "reactivate", "manage", "edit", "delete",
    "suspended", "expiry", "expire", "expires", "valid",
    "gérer", "gerer", "modifier", "supprimer", "renouveler",
    "réactiver", "reactiver", "expiration", "expire le", "valide",
    "续期", "重新激活", "恢复", "管理", "修改", "删除", "暂停", "过期", "到期",
)
NON_NAME_RE = re.compile("|".join(re.escape(word) for word in ACTION_WORDS), re.I)


def log(message):
    print(message, flush=True)


def now_cn():
    if ZoneInfo:
        try:
            return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def send_telegram(message):
    if not (TG_BOT_TOKEN and TG_CHAT_ID):
        log(f"[Telegram disabled] {message}")
        return
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT_ID, "text": message}, timeout=15,
        )
        response.raise_for_status()
        log(f"Telegram sent: {message[:50]}...")
    except Exception as exc:
        log(f"Failed to send Telegram: {exc}")


def text_of(element):
    try:
        return (element.get_attribute("innerText") or element.text or "").strip()
    except Exception:
        return ""


def shown(element):
    try:
        return element.is_displayed()
    except Exception:
        return False


def unique(elements):
    result, seen = [], set()
    for element in elements:
        try:
            key = element.id
        except Exception:
            continue
        if key not in seen:
            seen.add(key)
            result.append(element)
    return result


def descendants(root, selector):
    return root.find_elements(By.XPATH if selector.startswith(("/", ".//")) else By.CSS_SELECTOR, selector)


def normalize(value):
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def element_contains(parent, child):
    try:
        return bool(parent.find_elements(By.XPATH, ".//*[") and False)  # never used; avoids equality assumptions
    except Exception:
        pass
    try:
        return bool(parent._parent.execute_script("return arguments[0].contains(arguments[1]);", parent, child))
    except Exception:
        return False


def safe_click(sb, element, label):
    try:
        sb.driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", element)
        time.sleep(0.25)
        element.click()
        log(f"点击 {label}")
        return True
    except (ElementClickInterceptedException, StaleElementReferenceException, WebDriverException) as exc:
        try:
            sb.driver.execute_script("arguments[0].click();", element)
            log(f"点击 {label}（JavaScript）")
            return True
        except Exception as js_exc:
            log(f"无法点击 {label}: {exc}; {js_exc}")
            return False


def is_aclclouds_url(url):
    try:
        host = (urlsplit(url).hostname or "").lower()
    except Exception:
        return False
    return host == "aclclouds.com" or host.endswith(".aclclouds.com")


def is_login_url(url):
    path = (urlsplit(url).path or "").lower()
    return any(path == item or path.startswith(item + "/") for item in LOGIN_PATHS)


def current_base(sb):
    current = sb.get_current_url()
    parts = urlsplit(current)
    if parts.scheme and parts.netloc and is_aclclouds_url(current):
        return f"{parts.scheme}://{parts.netloc}"
    parts = urlsplit(LOGIN_URL)
    return f"{parts.scheme}://{parts.netloc}"


def verify_login_success(sb, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        url = sb.get_current_url()
        title = sb.get_title()
        log(f"登录状态检查 -> URL: {url}")
        log(f"登录状态检查 -> 标题: {title}")
        # 标题会随语言改变；离开登录路径且仍在 ACLClouds 域名即成功。
        if is_aclclouds_url(url) and not is_login_url(url):
            return True
        time.sleep(0.6)
    return False


def first_visible(driver, selectors, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for selector in selectors:
            by = By.XPATH if selector.startswith(("/", ".//")) else By.CSS_SELECTOR
            try:
                for element in driver.find_elements(by, selector):
                    if shown(element):
                        return element, selector
            except Exception:
                continue
        time.sleep(0.25)
    return None, ""


def visible_first(sb, selectors, timeout=10):
    """返回首个可见元素及其选择器；CSS 与 XPath 均支持。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for selector in selectors:
            try:
                by = By.XPATH if selector.startswith(("/", ".//")) else By.CSS_SELECTOR
                for element in sb.driver.find_elements(by, selector):
                    if shown(element):
                        return element, selector
            except Exception:
                continue
        time.sleep(0.25)
    return None, ""


def captcha_is_checked(sb):
    for selector in (
        "div.auth-captcha-inner[role='checkbox']",
        "div.auth-capcha-inner[role='checkbox']",
        "[role='checkbox']",
    ):
        try:
            for checkbox in sb.driver.find_elements(By.CSS_SELECTOR, selector):
                if shown(checkbox) and checkbox.get_attribute("aria-checked") == "true":
                    return True
        except Exception:
            continue
    return False


def challenge_element(sb):
    element, _ = visible_first(sb, (
        ".auth-captcha-challenge", ".auth-capcha-challenge",
        "//*[contains(@class, 'captcha') and contains(@class, 'challenge')]",
        "//*[contains(@aria-label, 'Click on ') or contains(@aria-label, 'Select ')]",
    ), timeout=1)
    return element


def challenge_target(challenge):
    for selector in (".auth-captcha-prompt strong", ".auth-capcha-prompt strong"):
        try:
            value = text_of(challenge.find_element(By.CSS_SELECTOR, selector))
            if value:
                return value
        except Exception:
            continue
    label = challenge.get_attribute("aria-label") or ""
    match = re.search(r"(?:Click on|Select)\s+(.+)", label, re.I)
    return match.group(1).strip() if match else ""


def challenge_options(challenge):
    for selector in (".auth-captcha-option", ".auth-capcha-option", ".//button", ".//a", ".//div[@role='button']"):
        try:
            by = By.XPATH if selector.startswith(".//") else By.CSS_SELECTOR
            choices = [item for item in challenge.find_elements(by, selector) if shown(item) and item.is_enabled()]
            if choices:
                return choices
        except Exception:
            continue
    return []


def option_label(option):
    value = text_of(option)
    if not value:
        for attr in ("aria-label", "title", "alt"):
            value = (option.get_attribute(attr) or "").strip()
            if value:
                break
    if not value:
        try:
            value = (option.find_element(By.TAG_NAME, "img").get_attribute("alt") or "").strip()
        except Exception:
            pass
    return value


def handle_captcha_challenge(sb, label="验证码", timeout=30):
    """保留原脚本的 ACLClouds 图片候选验证码流程。"""
    deadline = time.time() + timeout
    challenge = None
    while time.time() < deadline:
        if captcha_is_checked(sb):
            log(f"{label} 验证复选框已勾选，验证码流程已完成")
            return True
        challenge = challenge_element(sb)
        if challenge:
            log(f"{label} 检测到图形验证码挑战")
            break
        time.sleep(0.3)
    if not challenge:
        log(f"{label} 等待验证码挑战加载超时")
        return False

    initial_target = challenge_target(challenge)
    log(f"{label} 目标文本: {initial_target or '未识别'}")
    for attempt in range(8):
        if captcha_is_checked(sb):
            log(f"{label} 验证复选框已勾选，验证码流程已完成")
            return True
        challenge = challenge_element(sb)
        if not challenge:
            # 组件消失也可能表示验证完成；以 checkbox 状态再确认一次。
            time.sleep(0.5)
            return captcha_is_checked(sb)
        target = challenge_target(challenge) or initial_target
        options = challenge_options(challenge)
        if not options:
            log(f"{label} 当前挑战没有可点击选项，重试中...")
            time.sleep(0.8)
            continue
        candidate = next((item for item in options if target and target.casefold() in option_label(item).casefold()), options[0])
        log(f"{label} 点击候选选项 #{attempt + 1} ...")
        safe_click(sb, candidate, f"{label} 选项候选")
        time.sleep(4.5)
    if captcha_is_checked(sb):
        log(f"{label} 验证复选框已勾选，验证码流程已完成")
        return True
    log(f"{label} 多次尝试后仍未完成验证码")
    return False


def click_captcha_checkbox(sb, label="验证码", timeout=12):
    checkbox, selector = visible_first(sb, (
        "div.auth-captcha-inner[role='checkbox']",
        "div.auth-capcha-inner[role='checkbox']",
        "//div[contains(., 'Anti-bot confirmation')]//*[@role='checkbox']",
        "//div[contains(., 'I am not a robot')]//*[@role='checkbox']",
        "//div[contains(@class, 'modal') and contains(., 'Secured by ACLClouds')]//*[@role='checkbox']",
    ), timeout=timeout)
    if not checkbox:
        log(f"{label} 未找到人机验证复选框")
        return False
    if captcha_is_checked(sb):
        return True
    try:
        # 原脚本在这个控件上使用 uc_click；它比普通 WebDriver 点击更适合该站的挑战组件。
        if not selector.startswith("/"):
            sb.uc_click(selector)
        elif not safe_click(sb, checkbox, label):
            return False
    except Exception as exc:
        log(f"{label} UC 点击失败，改用普通点击: {exc}")
        if not safe_click(sb, checkbox, label):
            return False
    time.sleep(5)
    if not handle_captcha_challenge(sb, label):
        return False
    if captcha_is_checked(sb):
        log(f"{label} 验证通过")
        return True
    log(f"{label} 验证未完成")
    return False


def login(sb):
    if not EMAIL or not PASSWORD:
        raise RuntimeError("请设置 EMAIL 和 PASSWORD 环境变量。")
    log("开始登录流程...")
    # 先访问站点主页，让 ACLClouds 完成原有的重定向与前端初始化；
    # 直接打开 /auth/login 在代理较慢时可能拿到尚未挂载表单的页面。
    sb.open(current_base(sb))
    sb.wait_for_ready_state_complete()
    time.sleep(2)
    if not is_login_url(sb.get_current_url()):
        sb.open(LOGIN_URL)
        sb.wait_for_ready_state_complete()
        time.sleep(2)
    log(f"登录页 URL: {sb.get_current_url()}")
    log(f"登录页标题: {sb.get_title()}")
    # ACLClouds 当前登录页使用 #username / #password；其余选择器用于兼容后续页面改版。
    email, email_selector = first_visible(sb.driver, [
        "#username", "input[name='username']", "input[type='email']",
        "input[name='email']", "input[autocomplete='email']",
    ], timeout=30)
    password, password_selector = first_visible(sb.driver, [
        "#password", "input[type='password']", "input[name='password']",
        "input[autocomplete='current-password']",
    ], timeout=30)
    if not email or not password:
        try:
            summary = text_of(sb.driver.find_element(By.TAG_NAME, "body"))[:800]
        except Exception:
            summary = ""
        log(f"登录页诊断 URL: {sb.get_current_url()}")
        log(f"登录页诊断标题: {sb.get_title()}")
        log(f"登录页可见文本摘要: {summary}")
        raise RuntimeError("未找到邮箱或密码输入框，请检查登录页结构。")
    email.clear(); email.send_keys(EMAIL)
    password.clear(); password.send_keys(PASSWORD)
    log("邮箱输入框当前值: '***'")
    log(f"密码输入框当前值长度: {len(PASSWORD)}")
    if not click_captcha_checkbox(sb, "登录验证码"):
        raise RuntimeError("登录验证码未完成，未提交登录表单。")
    submit, selector = first_visible(sb.driver, ["button[type='submit']", "input[type='submit']"])
    if not submit:
        raise RuntimeError("未找到 Sign in 登录按钮。")
    safe_click(sb, submit, f"Sign in 使用: {selector}")
    if not verify_login_success(sb):
        raise RuntimeError(f"登录后仍未离开登录页: {sb.get_current_url()}")
    log("✅ 登录成功！")
    log(f"登录成功 URL: {sb.get_current_url()}")
    log(f"登录成功标题: {sb.get_title()}")


def action_xpath(words):
    conditions = []
    for word in words:
        if re.fullmatch(r"[A-Za-z ]+", word):
            conditions.append(
                "contains(translate(concat(normalize-space(.), ' ', @title, ' ', @aria-label), "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), %r)" % word.lower()
            )
        else:
            conditions.append("contains(concat(normalize-space(.), ' ', @title, ' ', @aria-label), %r)" % word)
    return ".//*[self::button or self::a or @role='button'][%s]" % " or ".join(conditions)


def card_from_child(sb, child):
    return sb.driver.execute_script("""
        const action = /^(?:manage|edit|delete|renew|reactivate|gérer|gerer|modifier|supprimer|renouveler|réactiver|reactiver|管理|修改|删除|续期|重新激活|恢复)$/i;
        let node = arguments[0];
        let best = null;
        let bestScore = -1;
        for (let i = 0; node && i < 12; i++, node = node.parentElement) {
          const cls = String(node.className || '').toLowerCase();
          const text = String(node.innerText || '').trim();
          const lines = text.split(/\\n+/).map(value => value.trim()).filter(Boolean);
          const hasName = lines.some(value => value.length <= 100 && !action.test(value));
          const buttons = node.querySelectorAll('button,a,[role="button"]').length;
          if (i > 0 && text.length >= 5 && buttons > 0) {
            let score = 0;
            if (/card|project|service|server/.test(cls)) score += 8;
            if (/item|row|grid/.test(cls)) score += 3;
            if (hasName) score += 12;
            score += Math.min(text.length, 500) / 100;
            if (score > bestScore) { best = node; bestScore = score; }
          }
        }
        return best || arguments[0].parentElement || arguments[0];
    """, child)


def meaningful_name(text):
    for line in (part.strip() for part in text.splitlines()):
        if not line or len(line) > 100 or NON_NAME_RE.search(line):
            continue
        if re.fullmatch(r"[\d\s:/.-]+", line):
            continue
        return line
    return ""


def expiry_from_text(text):
    for pattern in (
        r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?",
        r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?",
        r"\b\d+\s*(?:days?|hours?|minutes?|j(?:ours?)?|heures?|jours?|天|小时)\b",
    ):
        found = re.search(pattern, text, re.I)
        if found:
            return found.group(0)
    return "未知"


def get_project_name(card, idx=0):
    for selector in (".projects-card-title", "h1", "h2", "h3", "h4", "[class*='title']", "[class*='name']"):
        try:
            for element in card.find_elements(By.CSS_SELECTOR, selector):
                value = meaningful_name(text_of(element))
                if value:
                    return value
        except Exception:
            continue
    return meaningful_name(text_of(card)) or f"项目 #{idx}"


def get_project_expiry(card):
    return expiry_from_text(text_of(card))


def dedupe_project_cards(cards):
    kept, signatures = [], set()
    for card in unique(cards):
        if not shown(card) or len(text_of(card)) < 5:
            continue
        try:
            if any(sb_contains(card, old) for old in kept):
                continue
            nested = [old for old in kept if sb_contains(old, card)]
            for old in nested:
                kept.remove(old)
        except Exception:
            pass
        signature = (normalize(get_project_name(card)), normalize(get_project_expiry(card)))
        if signature not in signatures:
            signatures.add(signature); kept.append(card)
    return kept


def sb_contains(parent, child):
    try:
        return bool(parent._parent.execute_script("return arguments[0].contains(arguments[1])", parent, child))
    except Exception:
        try:
            return parent.id == child.id
        except Exception:
            return False


def find_project_cards(sb):
    candidate_selectors = [
        ".projects-card", "[class*='projects-card']", "[class*='project-card']",
        "[class*='service-card']", "[class*='server-card']", "[class*='service-item']",
        "[class*='project-item']", "[class*='server-item']", "article",
    ]
    cards = []
    for selector in candidate_selectors:
        try:
            for card in sb.driver.find_elements(By.CSS_SELECTOR, selector):
                if shown(card) and len(text_of(card)) >= 5 and any(word in normalize(text_of(card)) for word in ACTION_WORDS):
                    cards.append(card)
        except Exception as exc:
            if "Connection refused" in str(exc):
                raise
            continue
    # 法语页目前只有 Gérer / Modifier / Supprimer 时，以上条件仍能识别。
    for xpath in (action_xpath(("manage", "gérer", "gerer", "管理")), action_xpath(("edit", "delete", "modifier", "supprimer", "修改", "删除"))):
        try:
            for control in sb.driver.find_elements(By.XPATH, xpath):
                if shown(control):
                    cards.append(card_from_child(sb, control))
        except Exception as exc:
            if "Connection refused" in str(exc):
                raise
            continue
    return dedupe_project_cards(cards)


def find_renew_buttons(card):
    words = ("renew", "reactivate", "renouveler", "réactiver", "reactiver", "续期", "重新激活", "恢复")
    result = []
    try:
        # ACLClouds 法语页的续期操作可能是纯图标；文案常位于 tooltip 或 data 属性，
        # 而非按钮的可见文字或 title/aria-label。
        result.extend(card.find_elements(By.CSS_SELECTOR, (
            ".projects-renew-btn, [class*='renew'], [class*='reactivat'], "
            "[data-action*='renew'], [data-action*='reactivat'], "
            "[data-tooltip*='renew'], [data-tooltip*='renouvel'], [data-tooltip*='réactiv'], "
            "[data-testid*='renew'], [data-testid*='reactivat'], "
            "[data-original-title*='renew'], [data-original-title*='renouvel']"
        )))
        result.extend(card.find_elements(By.XPATH, action_xpath(words)))
    except Exception:
        pass
    return [element for element in unique(result) if shown(element)]


def find_manage_link(card):
    """在服务列表卡片中找到法语/英文/中文的管理入口。"""
    try:
        # 站点实际结构：<a class="... projects-service-action">Gérer</a>
        for element in card.find_elements(By.CSS_SELECTOR, "a.projects-service-action, a[href]"):
            if shown(element) and normalize(text_of(element)) in {"gérer", "gerer", "manage", "管理"}:
                return element
    except Exception:
        pass
    return None


def open_manage_page(sb, card, project_name):
    control = find_manage_link(card)
    if not control:
        return False
    try:
        href = (control.get_attribute("href") or "").strip()
    except Exception:
        href = ""
    try:
        if href:
            target_url = urljoin(sb.get_current_url(), href)
            log(f"[{project_name}] 进入管理页: {target_url}")
            sb.open(target_url)
        else:
            if not safe_click(sb, control, f"[{project_name}] Gérer/Manage"):
                return False
        sb.wait_for_ready_state_complete()
        time.sleep(2)
        log(f"[{project_name}] 管理页 URL: {sb.get_current_url()}")
        log(f"[{project_name}] 管理页标题: {sb.get_title()}")
        return True
    except Exception as exc:
        log(f"[{project_name}] 无法进入管理页: {exc}")
        return False


def log_service_button_diagnostics(card, project_name):
    """未找到续期按钮时，输出服务容器及祖先容器内图标按钮的可访问属性。"""
    try:
        rows = card._parent.execute_script("""
            let node = arguments[0];
            const seen = new Set(), out = [];
            for (let depth = 0; node && depth < 5; depth++, node = node.parentElement) {
              for (const button of node.querySelectorAll('button,a,[role="button"]')) {
                if (seen.has(button)) continue;
                seen.add(button);
                const style = window.getComputedStyle(button);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                out.push({
                  depth,
                  tag: button.tagName.toLowerCase(),
                  text: (button.innerText || '').trim(),
                  title: button.getAttribute('title') || '',
                  aria: button.getAttribute('aria-label') || '',
                  tooltip: button.getAttribute('data-tooltip') || '',
                  action: button.getAttribute('data-action') || '',
                  testid: button.getAttribute('data-testid') || '',
                  cls: String(button.className || '')
                });
              }
            }
            return out.slice(0, 30);
        """, card)
        log(f"[{project_name}] 续期按钮诊断: {rows}")
    except Exception as exc:
        log(f"[{project_name}] 无法读取续期按钮诊断: {exc}")


def log_current_page_button_diagnostics(sb, project_name):
    """详情页使用当前 document，而不是已失效的列表卡片元素。"""
    try:
        rows = sb.driver.execute_script("""
            return Array.from(document.querySelectorAll('button,a,[role="button"]'))
              .filter(el => {
                const s = getComputedStyle(el);
                return s.display !== 'none' && s.visibility !== 'hidden';
              })
              .slice(0, 60)
              .map(el => ({
                tag: el.tagName.toLowerCase(), text: (el.innerText || '').trim(),
                title: el.getAttribute('title') || '', aria: el.getAttribute('aria-label') || '',
                tooltip: el.getAttribute('data-tooltip') || '', action: el.getAttribute('data-action') || '',
                testid: el.getAttribute('data-testid') || '', cls: String(el.className || ''),
                href: el.getAttribute('href') || ''
              }));
        """)
        log(f"[{project_name}] 管理页按钮诊断: {rows}")
    except Exception as exc:
        log(f"[{project_name}] 无法读取管理页按钮诊断: {exc}")


def wait_for_renew_result(sb, before_expiry, timeout=25):
    success_words = ("success", "renewed", "reactivated", "succès", "renouvelé", "réactivé", "成功", "续期成功")
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = normalize(text_of(sb.driver.find_element(By.TAG_NAME, "body")))
        if any(word in body for word in success_words):
            return True, "页面显示成功提示"
        time.sleep(0.5)
    return False, "未观察到续期成功提示"


def renew_projects(sb):
    projects_url = current_base(sb) + PROJECTS_PATH
    log(f"📍 准备进入项目页: {projects_url}")
    sb.open(projects_url)
    # 与原脚本一致：项目页为前端动态页面，先等待 document ready，避免
    # 刚导航完成就开始读取卡片时 UC/ChromeDriver 会话被提前关闭。
    sb.wait_for_ready_state_complete()
    time.sleep(2)
    log(f"📍 当前项目页 URL: {sb.get_current_url()}")
    log(f"📄 当前项目页标题: {sb.get_title()}")
    try:
        cards = find_project_cards(sb)
    except (WebDriverException, requests.exceptions.RequestException) as exc:
        raise RuntimeError(
            "浏览器驱动在读取项目页时已断开。请保留本次工作流日志中的 Chrome/ChromeDriver 输出，"
            f"具体错误: {exc}"
        ) from exc
    if not cards:
        excerpt = text_of(sb.driver.find_element(By.TAG_NAME, "body"))[:1200]
        log("❌ 未找到项目卡片。")
        log(f"项目页可见文本摘要: {excerpt}")
        send_telegram("⚠️ 未找到项目卡片，请检查页面结构。")
        return
    log(f"找到 {len(cards)} 个项目卡片。")
    outcomes = []
    for index in range(1, len(cards) + 1):
        cards = find_project_cards(sb)
        if index > len(cards):
            break
        card = cards[index - 1]
        name, expiry = get_project_name(card, index), get_project_expiry(card)
        buttons = find_renew_buttons(card)
        # 反推到的容器有时只是服务的操作栏；此时在项目页全局再找一次
        # 带有“续期/重新激活”语义属性的图标按钮。
        if not buttons:
            buttons = find_renew_buttons(sb.driver)
        # 列表页只提供 Gérer / Modifier / Supprimer 时，续期操作位于管理详情页。
        opened_manage_page = False
        if not buttons and open_manage_page(sb, card, name):
            opened_manage_page = True
            buttons = find_renew_buttons(sb.driver)
        log(f"[{name}] 当前过期: {expiry}")
        if not buttons:
            if opened_manage_page:
                log_current_page_button_diagnostics(sb, name)
            else:
                log_service_button_diagnostics(card, name)
            outcomes.append(f"{name}: 无可用续期按钮")
            continue
        if DRY_RUN:
            outcomes.append(f"{name}: 检测到续期按钮（DRY_RUN 未点击）")
            continue
        if safe_click(sb, buttons[0], f"[{name}] 续期/重新激活"):
            ok, detail = wait_for_renew_result(sb, expiry)
            outcomes.append(f"{name}: {'✅ ' if ok else '⚠️ '}{detail}")
        else:
            outcomes.append(f"{name}: ❌ 无法点击续期按钮")
    send_telegram("ACLClouds 续期检查\n" + "\n".join(outcomes))


def main():
    log(f"ACLClouds 续期任务开始：{now_cn()}")
    if PROXY:
        log(f"🔗 挂载代理: {PROXY}")
    # 与原脚本一致，使用 SeleniumBase 的 UC 浏览器模式。
    options = {"uc": True, "headless": HEADLESS}
    if PROXY:
        options["proxy"] = PROXY
    try:
        with SB(**options) as sb:
            login(sb)
            renew_projects(sb)
    except Exception as exc:
        log(f"❌ 任务失败: {exc}")
        send_telegram(f"❌ ACLClouds 续期任务失败：{exc}")
        raise


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
