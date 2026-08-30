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
from urllib.parse import urlsplit

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
PROXY = os.getenv("PROXY", "").strip()
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


def solve_visible_click_challenge(sb, timeout=20):
    """处理页面上以文字候选项呈现的既有登录挑战；没有挑战时直接返回。"""
    driver = sb.driver
    challenge_text = " ".join(text_of(e) for e in driver.find_elements(By.CSS_SELECTOR, "body")[:1])
    if not re.search(r"captcha|vérification|verification|验证码|challenge", challenge_text, re.I):
        return True
    log("登录验证码 检测到图形/文字验证码挑战")
    # 只使用页面已暴露的可访问文本，不尝试绕过外部 CAPTCHA 服务。
    labels = driver.find_elements(By.CSS_SELECTOR, "label, button, [role='button'], [role='checkbox']")
    targets = [text_of(e) for e in labels if shown(e) and text_of(e)]
    prompt = " ".join(targets[:20])
    target_match = re.search(r"(?:select|choose|click|点击|选择).*?[:：]\s*([^\n,.;]{2,40})", prompt, re.I)
    if not target_match:
        log("登录验证码 未识别到可访问的目标文本；请在浏览器中人工完成验证码。")
        return True
    target = normalize(target_match.group(1))
    log(f"登录验证码 目标文本: {target_match.group(1).strip()}")
    clicked = 0
    for candidate in labels:
        value = normalize(text_of(candidate))
        if value and (value == target or target in value):
            if safe_click(sb, candidate, f"验证码候选项 #{clicked + 1}"):
                clicked += 1
    if clicked:
        time.sleep(1)
    return True


def login(sb):
    if not EMAIL or not PASSWORD:
        raise RuntimeError("请设置 EMAIL 和 PASSWORD 环境变量。")
    log("开始登录流程...")
    sb.open(LOGIN_URL)
    email, email_selector = first_visible(sb.driver, [
        "input[type='email']", "input[name='email']", "input[autocomplete='email']",
    ])
    password, password_selector = first_visible(sb.driver, [
        "input[type='password']", "input[name='password']", "input[autocomplete='current-password']",
    ])
    if not email or not password:
        raise RuntimeError("未找到邮箱或密码输入框，请检查登录页结构。")
    email.clear(); email.send_keys(EMAIL)
    password.clear(); password.send_keys(PASSWORD)
    log("邮箱输入框当前值: '***'")
    log(f"密码输入框当前值长度: {len(PASSWORD)}")
    solve_visible_click_challenge(sb)
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
        let node = arguments[0];
        for (let i = 0; node && i < 12; i++, node = node.parentElement) {
          const cls = String(node.className || '').toLowerCase();
          const text = String(node.innerText || '').trim();
          const buttons = node.querySelectorAll('button,a,[role="button"]').length;
          if (i > 0 && text.length >= 5 && buttons > 0 && /card|project|service|server|item|row|grid/.test(cls)) return node;
        }
        return arguments[0].parentElement;
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
        except Exception:
            continue
    # 法语页目前只有 Gérer / Modifier / Supprimer 时，以上条件仍能识别。
    for xpath in (action_xpath(("manage", "gérer", "gerer", "管理")), action_xpath(("edit", "delete", "modifier", "supprimer", "修改", "删除"))):
        try:
            for control in sb.driver.find_elements(By.XPATH, xpath):
                if shown(control):
                    cards.append(card_from_child(sb, control))
        except Exception:
            continue
    return dedupe_project_cards(cards)


def find_renew_buttons(card):
    words = ("renew", "reactivate", "renouveler", "réactiver", "reactiver", "续期", "重新激活", "恢复")
    result = []
    try:
        result.extend(card.find_elements(By.CSS_SELECTOR, ".projects-renew-btn, [class*='renew'], [class*='reactivat']"))
        result.extend(card.find_elements(By.XPATH, action_xpath(words)))
    except Exception:
        pass
    return [element for element in unique(result) if shown(element)]


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
    time.sleep(2)
    log(f"📍 当前项目页 URL: {sb.get_current_url()}")
    log(f"📄 当前项目页标题: {sb.get_title()}")
    cards = find_project_cards(sb)
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
        log(f"[{name}] 当前过期: {expiry}")
        if not buttons:
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
    options = {"headless": HEADLESS}
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
