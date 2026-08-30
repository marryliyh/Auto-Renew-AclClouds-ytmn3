#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ACLClouds project renewal notifier.

Environment variables:
  EMAIL, PASSWORD                 ACLClouds control-panel credentials
  TG_BOT_TOKEN, TG_CHAT_ID        Optional Telegram notification settings
  PROXY                           Optional Selenium proxy, e.g. socks5://127.0.0.1:1080
  HEADLESS                        1/true for headless Chromium (default: false)
  CAPTCHA_WAIT_SECONDS            Time to allow a human to complete a displayed captcha

The control-panel session is deliberately checked only on dash.aclclouds.com.
The public website aclclouds.com/en/ is never treated as an authenticated session.
"""

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from seleniumbase import SB
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.common.by import By


EMAIL = os.getenv("EMAIL", "").strip()
PASSWORD = os.getenv("PASSWORD", "")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()
PROXY = os.getenv("PROXY", "").strip()
HEADLESS = os.getenv("HEADLESS", "false").lower() in {"1", "true", "yes"}
CAPTCHA_WAIT_SECONDS = int(os.getenv("CAPTCHA_WAIT_SECONDS", "120"))

CONTROL_PANEL_BASE = "https://dash.aclclouds.com"
LOGIN_PATH = "/auth/login"
LOGIN_URL = f"{CONTROL_PANEL_BASE}/en{LOGIN_PATH}"
PROJECTS_URL = f"{CONTROL_PANEL_BASE}/en/dashboard/projects"

ACTION_WORDS = (
    "renew", "renewal", "reactivate", "manage", "edit", "delete",
    "renouveler", "renouvellement", "réactiver", "reactiver", "gérer",
    "gerer", "modifier", "supprimer", "续期", "重新激活", "恢复", "管理",
    "修改", "删除",
)
EXPIRY_WORDS = (
    "expiry", "expires", "expire", "expiration", "valid", "remaining",
    "time left", "renouvellement", "expir", "valide", "restant", "剩余",
    "过期", "到期", "有效期",
)


@dataclass
class ProjectInfo:
    name: str
    absolute_expiry: str
    remaining: str
    has_renew_action: bool
    action_label: str = ""

    @property
    def expiry_display(self):
        if self.absolute_expiry and self.remaining:
            return f"{self.absolute_expiry}（剩余 {self.remaining}）"
        return self.absolute_expiry or self.remaining or "未知"


def beijing_time_str():
    try:
        zone = ZoneInfo("Asia/Shanghai")
    except Exception:
        zone = timezone(timedelta(hours=8))
    return datetime.now(zone).strftime("%Y-%m-%d %H:%M:%S")


def send_telegram(message):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print(f"[Telegram disabled] {message}")
        return
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT_ID, "text": message},
            timeout=15,
        )
        response.raise_for_status()
        print(f"Telegram sent: {message[:100]}...")
    except Exception as exc:
        print(f"Telegram 发送失败: {exc}")


def normalize(text):
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def element_text(element):
    try:
        return normalize(element.text)
    except Exception:
        return ""


def safe_click(sb, element, label):
    try:
        sb.driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element
        )
        sb.sleep(0.3)
        element.click()
        return True
    except (ElementClickInterceptedException, StaleElementReferenceException, WebDriverException):
        try:
            sb.driver.execute_script("arguments[0].click();", element)
            return True
        except Exception as exc:
            print(f"{label} 点击失败: {exc}")
            return False
    except Exception as exc:
        print(f"{label} 点击失败: {exc}")
        return False


def current_url(sb):
    try:
        return sb.get_current_url() or ""
    except Exception:
        return ""


def is_control_panel_url(url):
    try:
        return urlparse(url).hostname.lower() == "dash.aclclouds.com"
    except Exception:
        return False


def is_login_page(sb):
    return LOGIN_PATH in current_url(sb).lower()


def has_visible_login_form(sb):
    for selector in ("#username", "input[name='username']", "input[name='email']"):
        try:
            if any(item.is_displayed() for item in sb.driver.find_elements(By.CSS_SELECTOR, selector)):
                return True
        except Exception:
            continue
    return False


def has_projects_page_content(sb):
    url = current_url(sb).lower()
    if "/dashboard/projects" in url and not is_login_page(sb):
        return True
    try:
        text = element_text(sb.driver.find_element(By.TAG_NAME, "body")).lower()
    except Exception:
        return False
    return any(word in text for word in ("my services", "mes services", "projects", "services"))


def dashboard_session_is_valid(sb):
    """A valid session must be on dash.aclclouds.com and outside /auth/login."""
    url = current_url(sb)
    return is_control_panel_url(url) and not is_login_page(sb) and not has_visible_login_form(sb)


def wait_for_dashboard_login(sb, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if dashboard_session_is_valid(sb):
            return True
        sb.sleep(0.5)
    return False


def find_first_visible(sb, selectors, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        for selector in selectors:
            try:
                elements = sb.driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    if element.is_displayed():
                        return element
            except Exception:
                continue
        sb.sleep(0.25)
    return None


def submit_login(sb):
    if not EMAIL or not PASSWORD:
        raise RuntimeError("请设置 EMAIL 和 PASSWORD 环境变量。")

    print("开始控制面板登录流程...")
    sb.open(LOGIN_URL)
    sb.sleep(1)

    if dashboard_session_is_valid(sb):
        print("控制面板会话仍有效。")
        return True

    username = find_first_visible(sb, ("#username", "input[name='username']", "input[name='email']"))
    password = find_first_visible(sb, ("#password", "input[name='password']", "input[type='password']"))
    if not username or not password:
        raise RuntimeError(f"未找到控制面板登录表单，当前 URL: {current_url(sb)}")

    username.clear()
    username.send_keys(EMAIL)
    password.clear()
    password.send_keys(PASSWORD)

    # Clicking the checkbox is ordinary page interaction. If it opens an image challenge,
    # this script only waits for a human to complete it; it does not solve the challenge.
    checkbox = find_first_visible(sb, ("div.auth-captcha-inner[role='checkbox']", "[role='checkbox']"), timeout=3)
    if checkbox:
        safe_click(sb, checkbox, "登录验证码复选框")
        challenge = find_first_visible(sb, (".auth-captcha-challenge", ".auth-capcha-challenge"), timeout=2)
        if challenge:
            print(f"检测到图形验证码，请在 {CAPTCHA_WAIT_SECONDS} 秒内手动完成。")
            end = time.time() + CAPTCHA_WAIT_SECONDS
            while time.time() < end:
                try:
                    if checkbox.get_attribute("aria-checked") == "true":
                        break
                except Exception:
                    pass
                sb.sleep(1)

    submit = find_first_visible(sb, ("button[type='submit']", "input[type='submit']"), timeout=5)
    if not submit or not safe_click(sb, submit, "Sign in"):
        raise RuntimeError("未找到或无法点击登录提交按钮。")

    if not wait_for_dashboard_login(sb, timeout=35):
        raise RuntimeError(
            "登录后未获得 dash.aclclouds.com 控制面板会话；"
            f"当前 URL: {current_url(sb)}。请检查账号、密码或验证码。"
        )
    print(f"✅ 控制面板登录成功: {current_url(sb)}")
    return True


def open_projects_page(sb):
    print(f"📍 准备进入项目页: {PROJECTS_URL}")
    sb.open(PROJECTS_URL)
    sb.sleep(2)
    url = current_url(sb)
    print(f"📍 当前项目页 URL: {url}")
    try:
        print(f"📄 当前项目页标题: {sb.get_title()}")
    except Exception:
        pass

    # A redirect to dash.aclclouds.com/auth/login means an expired control-panel
    # session, not automatically bad credentials.
    if is_login_page(sb) or not dashboard_session_is_valid(sb):
        print("⚠️ 项目页被重定向到控制面板登录页，正在重新登录。")
        submit_login(sb)
        sb.open(PROJECTS_URL)
        sb.sleep(2)
    if is_login_page(sb) or not has_projects_page_content(sb):
        raise RuntimeError(f"无法访问控制面板项目页: {current_url(sb)}")


def unique_elements(elements):
    result, seen = [], set()
    for element in elements:
        try:
            key = element.id
        except Exception:
            key = id(element)
        if key not in seen:
            seen.add(key)
            result.append(element)
    return result


def action_text(element):
    values = [element_text(element)]
    for attr in ("title", "aria-label", "data-tooltip", "data-title"):
        try:
            values.append(element.get_attribute(attr) or "")
        except Exception:
            pass
    return normalize(" ".join(values))


def is_action_element(element, words):
    return any(word in action_text(element).lower() for word in words)


def card_from_action(sb, action):
    """Find the closest reasonable project-card ancestor for a button or link."""
    try:
        return sb.driver.execute_script(
            """
            let node = arguments[0];
            for (let depth = 0; node && depth < 10; depth++, node = node.parentElement) {
              const cls = String(node.className || '').toLowerCase();
              const text = String(node.innerText || '').trim();
              if (depth > 0 && text.length >= 3 &&
                  /(project|service|card|server|item|row|tile|panel)/.test(cls)) return node;
            }
            return arguments[0].parentElement;
            """,
            action,
        )
    except Exception:
        return None


def find_project_cards(sb):
    cards = []
    action_selectors = ("button", "a", "[role='button']")
    for selector in action_selectors:
        try:
            for action in sb.driver.find_elements(By.CSS_SELECTOR, selector):
                if action.is_displayed() and is_action_element(action, ACTION_WORDS):
                    card = card_from_action(sb, action)
                    if card is not None:
                        cards.append(card)
        except Exception:
            continue

    # Fallback for cards that expose no operation until opened.
    if not cards:
        for selector in (
            ".projects-card", "[class*='project'][class*='card']",
            "[class*='service'][class*='card']", "[class*='service-item']", "article",
        ):
            try:
                cards.extend(element for element in sb.driver.find_elements(By.CSS_SELECTOR, selector) if element.is_displayed())
            except Exception:
                continue

    # Nested generic containers are common; retain the smallest useful ancestor only.
    result = []
    for card in unique_elements(cards):
        text = element_text(card)
        if len(text) < 3:
            continue
        if any(card in existing.find_elements(By.XPATH, ".//*") for existing in result):
            continue
        result = [existing for existing in result if existing not in card.find_elements(By.XPATH, ".//*")]
        result.append(card)
    return result


def extract_absolute_date(text):
    patterns = (
        r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?\b",
        r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?\b",
        r"\b\d{1,2}\s+(?:janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\s+\d{4}\b",
        r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.I)
        if match:
            return match.group(0)
    return ""


def extract_remaining(text):
    text = normalize(text)
    patterns = (
        r"\b\d+\s*(?:j|jours?|d|days?)(?:\s+\d+\s*(?:h|heures?|hours?|hrs?))?(?:\s+\d+\s*(?:m|min(?:utes)?))?\b",
        r"\b\d+\s*(?:h|heures?|hours?|hrs?)(?:\s+\d+\s*(?:m|min(?:utes)?))?\b",
        r"\b\d+\s*(?:m|min(?:utes)?)\b",
        r"\d+\s*天(?:\s*\d+\s*小时)?",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(0)
    return ""


def expiry_candidate_texts(card):
    values = [element_text(card)]
    for element in card.find_elements(By.CSS_SELECTOR, "*"):
        text = element_text(element)
        attrs = " ".join(
            (element.get_attribute(name) or "")
            for name in ("title", "datetime", "data-expiry", "data-expiration", "data-expires", "aria-label")
        )
        combined = normalize(f"{text} {attrs}")
        if any(word in combined.lower() for word in EXPIRY_WORDS):
            values.append(combined)
    return values


def project_name(card, index):
    for selector in (".projects-card-title", ".project-title", ".service-title", ".project-name", "h1", "h2", "h3", "h4"):
        try:
            for element in card.find_elements(By.CSS_SELECTOR, selector):
                text = element_text(element)
                if text and len(text) <= 100 and not is_action_element(element, ACTION_WORDS):
                    return text
        except Exception:
            continue
    for line in element_text(card).splitlines():
        line = line.strip()
        lower = line.lower()
        if line and len(line) <= 100 and not any(word in lower for word in ACTION_WORDS + EXPIRY_WORDS):
            if not extract_absolute_date(line) and not extract_remaining(line):
                return line
    return f"项目 #{index}"


def renewal_buttons(card):
    found = []
    for selector in ("button", "a", "[role='button']"):
        try:
            found.extend(card.find_elements(By.CSS_SELECTOR, selector))
        except Exception:
            pass
    return [element for element in unique_elements(found) if is_action_element(element, ("renew", "reactivate", "renouveler", "réactiver", "reactiver", "续期", "重新激活", "恢复"))]


def inspect_project(card, index):
    absolute, remaining = "", ""
    for candidate in expiry_candidate_texts(card):
        absolute = absolute or extract_absolute_date(candidate)
        remaining = remaining or extract_remaining(candidate)
    buttons = renewal_buttons(card)
    return ProjectInfo(project_name(card, index), absolute, remaining, bool(buttons), action_text(buttons[0]) if buttons else "")


def visible_page_message(sb):
    try:
        body = element_text(sb.driver.find_element(By.TAG_NAME, "body"))
    except Exception:
        return ""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    matches = [line for line in lines if re.search(r"success|successfully|failed|error|unable|échec|erreur|réussi|成功|失败", line, re.I)]
    return " | ".join(matches[:3])


def wait_for_renew_result(sb, before, project_index, timeout=35):
    end = time.time() + timeout
    last_reason = "未在等待时间内看到状态变更。"
    while time.time() < end:
        message = visible_page_message(sb)
        if re.search(r"failed|error|unable|échec|erreur|失败", message, re.I):
            return "failed", before, message
        try:
            cards = find_project_cards(sb)
            if len(cards) >= project_index:
                after = inspect_project(cards[project_index - 1], project_index)
                if re.search(r"success|successfully|réussi|成功", message, re.I):
                    return "success", after, message
                if after.expiry_display != before.expiry_display:
                    return "success", after, "过期时间/剩余时间已更新。"
                if not after.has_renew_action:
                    return "success", after, "续期操作已不再显示。"
        except Exception as exc:
            last_reason = str(exc)
        sb.sleep(1)
    return "unconfirmed", before, last_reason


def notify_project(prefix, project, detail):
    send_telegram(
        "🇫🇷 ACLClouds 续期通知\n\n"
        f"{prefix}\n"
        f"📦 项目: {project.name}\n"
        f"⏱️ 当前过期时间: {project.expiry_display}\n"
        f"👤 登录账户: {EMAIL}\n"
        f"📝 说明: {detail}\n"
        f"⏱️ 运行时间: {beijing_time_str()}"
    )


def process_projects(sb):
    cards = find_project_cards(sb)
    if not cards:
        raise RuntimeError("未找到项目卡片；请根据页面实际 HTML 调整卡片选择器。")
    print(f"找到 {len(cards)} 个项目卡片。")

    for index in range(1, len(cards) + 1):
        cards = find_project_cards(sb)  # avoid stale elements after prior actions
        if len(cards) < index:
            print(f"项目 #{index} 在刷新后不再存在，跳过。")
            continue
        card = cards[index - 1]
        project = inspect_project(card, index)
        print(f"[{project.name}] 当前过期: {project.expiry_display}")

        buttons = renewal_buttons(card)
        if not buttons:
            print("无 Renew/Reactivate 按钮，提示: 未到续期时间")
            notify_project("⏳ 未到续期时间", project, "页面尚未显示 Renew / Reactivate 操作。")
            continue

        label = project.action_label or "Renew"
        print(f"[{project.name}] 点击 {label}...")
        if not safe_click(sb, buttons[0], f"{project.name} {label}"):
            notify_project("❌ 续期失败", project, f"无法点击 {label} 按钮。")
            continue

        # If the website asks for a human confirmation/captcha after the click, wait
        # rather than attempting to solve or bypass it.
        if find_first_visible(sb, (".auth-captcha-challenge", ".auth-capcha-challenge"), timeout=2):
            print(f"续期出现图形验证码，请在 {CAPTCHA_WAIT_SECONDS} 秒内手动完成。")
            sb.sleep(CAPTCHA_WAIT_SECONDS)

        status, after, reason = wait_for_renew_result(sb, project, index)
        if status == "success":
            send_telegram(
                "🇫🇷 ACLClouds 续期通知\n\n"
                "✅ 续期成功\n"
                f"📦 项目: {after.name}\n"
                f"⏱️ 新过期时间: {after.expiry_display}\n"
                f"📌 状态: {reason}\n"
                f"👤 登录账户: {EMAIL}\n"
                f"⏱️ 运行时间: {beijing_time_str()}"
            )
            print(f"[{after.name}] ✅ 续期成功: {after.expiry_display}")
        elif status == "failed":
            notify_project("❌ 续期失败", project, reason or "页面返回失败状态。")
            print(f"[{project.name}] ❌ 续期失败: {reason}")
        else:
            notify_project("⚠️ 续期未确认", project, reason)
            print(f"[{project.name}] ⚠️ 续期未确认: {reason}")


def main():
    options = {"uc": True, "headless": HEADLESS}
    if PROXY:
        options["proxy"] = PROXY
        print(f"🔗 使用代理: {PROXY}")
    with SB(**options) as sb:
        submit_login(sb)
        open_projects_page(sb)
        process_projects(sb)
    print("所有项目处理完成。")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        message = f"⚠️ ACLClouds 脚本异常\n\n原因: {exc}\n时间: {beijing_time_str()}"
        print(message)
        send_telegram(message)
        raise
