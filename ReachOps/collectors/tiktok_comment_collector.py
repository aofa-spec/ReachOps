# -*- coding: utf-8 -*-
from __future__ import annotations

import time

from .base import CollectorAdapter
from .normalizer import (
    absolute_tiktok_url,
    detect_text_language,
    is_comment_noise_text,
    is_placeholder_comment_text,
    normalize_comment_text,
    normalize_tiktok_username,
    parse_count,
)


class TikTokCommentCollector(CollectorAdapter):
    def collect(self, driver, task, context):
        limit = int(context.get("limit") or 50)
        warm_stats = self._warm_comments(driver, limit)
        page_state = self._inspect_comment_state(driver, warm_stats)
        self.last_diagnostics = page_state
        try:
            rows = driver.execute_script(
                """
                function textOf(node) {
                  return String((node && (node.innerText || node.textContent)) || '').replace(/\\s+/g, ' ').trim();
                }
                function hasCommentMarker(node) {
                  if (!node) return false;
                  const marker = [
                    node.getAttribute('data-e2e') || '',
                    node.getAttribute('aria-label') || '',
                    node.className || ''
                  ].join(' ').toLowerCase();
                  return /comment|coment|reply|resposta|respuesta/.test(marker);
                }
                function boundedCommentRoot(link) {
                  let node = link;
                  let best = null;
                  for (let depth = 0; node && depth < 9; depth++) {
                    const text = textOf(node);
                    const links = node.querySelectorAll ? node.querySelectorAll('a[href*="/@"]').length : 0;
                    const marker = hasCommentMarker(node);
                    const interactionText = /reply|replies|responder|respostas?|respuesta|ver respostas?|view replies?|like/i.test(text);
                    if (text.length >= 8 && text.length <= 900 && links <= 3 && (marker || interactionText)) {
                      best = node;
                      break;
                    }
                    node = node.parentElement;
                  }
                  return best;
                }
                function cleanLines(text) {
                  return String(text || '')
                    .split(/\\n+/)
                    .map((line) => line.replace(/\\s+/g, ' ').trim())
                    .filter((line) => line && !/^(follow|following|seguir|seguindo|responder|reply|view replies?|ver respostas?|like|share)$/i.test(line));
                }
                const strictRoots = Array.from(document.querySelectorAll(
                  '[data-e2e*="comment-level"], [data-e2e*="comment-item"], [data-e2e*="comment-list"] [role="listitem"], div[class*="CommentItem"], div[class*="DivCommentItem"]'
                ));
                const strictLinks = strictRoots.flatMap((node) => Array.from(node.querySelectorAll('a[href*="/@"]')));
                const candidateLinks = strictLinks.length
                  ? strictLinks
                  : Array.from(document.querySelectorAll('a[href*="/@"]')).filter((link) => Boolean(boundedCommentRoot(link)));
                const nodes = candidateLinks
                  .map((link) => ({link, root: boundedCommentRoot(link)}))
                  .filter((item) => {
                    const text = textOf(item.root);
                    return item.root && text.length > 0 && text.length < 1200;
                  });
                const seen = new Set();
                const rows = [];
                let duplicateCount = 0;
                let skippedNoUser = 0;
                let skippedNoText = 0;
                for (let idx = 0; idx < nodes.length; idx++) {
                  const node = nodes[idx].root;
                  const link = nodes[idx].link || node.querySelector('a[href*="/@"]') || node.closest('a[href*="/@"]');
                  const usernameFromHref = link ? (link.href.split('/@').pop().split(/[/?#]/)[0]) : '';
                  const username = link ? ((link.innerText || usernameFromHref || '').trim()) : usernameFromHref;
                  const usernameLower = String(username || usernameFromHref || '').trim().toLowerCase();
                  const aria = node.getAttribute('aria-label') || '';
                  const textNodes = Array.from(node.querySelectorAll('[data-e2e*="comment-level"], [data-e2e*="comment-text"], p, span, div'));
                  const text = (cleanLines(textNodes
                    .map((n) => n.innerText || '')
                    .filter((value) => value && value.trim().length > 1)
                    .join('\\n'))
                    .filter((line) => {
                      const lower = line.toLowerCase();
                      return lower !== usernameLower && !lower.includes('@' + usernameLower);
                    })
                    .sort((a, b) => b.length - a.length)[0] || '').trim();
                  const fallbackText = (cleanLines(node.innerText || aria)
                    .filter((line) => {
                      const lower = line.toLowerCase();
                      return lower !== usernameLower && !lower.includes('@' + usernameLower);
                    })
                    .sort((a, b) => b.length - a.length)[0] || '').trim();
                  const finalText = text || fallbackText;
                  const likeNode = node.querySelector('[data-e2e*="like-count"], strong, [class*="like-count"]');
                  const replyText = node.innerText || '';
                  const profileUrl = link ? link.href : (usernameFromHref ? `/@${usernameFromHref}` : '');
                  const normalizedUser = String(username || usernameFromHref || '').trim().toLowerCase();
                  const normalizedText = String(finalText || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                  const key = `${normalizedUser}|${normalizedText}`;
                  if (!username) {
                    skippedNoUser += 1;
                    continue;
                  }
                  if (!finalText) {
                    skippedNoText += 1;
                    continue;
                  }
                  if (seen.has(key)) {
                    duplicateCount += 1;
                    continue;
                  }
                  seen.add(key);
                  rows.push({
                    username,
                    profile_url: profileUrl,
                    comment_text: finalText,
                    comment_likes: likeNode ? likeNode.innerText : '',
                    reply_count: replyText,
                    node_index: idx,
                    duplicate_count: duplicateCount,
                    node_text_length: replyText.length,
                    skipped_no_user: skippedNoUser,
                    skipped_no_text: skippedNoText,
                    visible_node_count: nodes.length
                  });
                }
                return rows;
                """
            )
        except Exception:
            rows = []
        comments = []
        seen = set()
        duplicate_rows = 0
        for row in (rows or [])[:limit]:
            reply_count = 0
            raw_reply = str(row.get("reply_count") or "")
            reply_words = ["reply", "replies", "responder", "respuestas", "resposta", "respostas", "ver respostas"]
            if any(word in raw_reply.lower() for word in reply_words):
                reply_count = 1
            username = normalize_tiktok_username(row.get("profile_url") or row.get("username") or "")
            comment_text = normalize_comment_text(row.get("comment_text") or "")
            if not username or not comment_text or is_placeholder_comment_text(comment_text) or is_comment_noise_text(comment_text):
                continue
            key = (username, comment_text)
            if key in seen:
                duplicate_rows += 1
                continue
            seen.add(key)
            profile_url = absolute_tiktok_url(row.get("profile_url") or f"/@{username}")
            profile_completed = bool(profile_url and username and f"/@{username}" in profile_url)
            if not profile_completed and username:
                profile_url = absolute_tiktok_url(f"/@{username}")
                profile_completed = True
            language = detect_text_language(comment_text)
            comments.append(
                {
                    "username": username,
                    "profile_url": profile_url,
                    "comment_text": comment_text,
                    "comment_likes": parse_count(row.get("comment_likes")),
                    "reply_count": reply_count,
                    "comment_language": language,
                    "author_profile_completed": profile_completed,
                    "collector_level": self.level,
                    "source_path": str(task.get("content", {}).get("video_url") or task.get("content", {}).get("id") or ""),
                    "raw_meta": {
                        "node_index": row.get("node_index"),
                        "node_text_length": row.get("node_text_length"),
                        "duplicate_count_before_row": row.get("duplicate_count", 0),
                        "duplicate_rows_in_python": duplicate_rows,
                        "visible_node_count": row.get("visible_node_count", 0),
                        "skipped_no_user": row.get("skipped_no_user", 0),
                        "skipped_no_text": row.get("skipped_no_text", 0),
                        "scroll_rounds": warm_stats.get("scroll_rounds", 0),
                        "stable_rounds": warm_stats.get("stable_rounds", 0),
                        "max_visible_nodes": warm_stats.get("max_visible_nodes", 0),
                        "visible_node_history": warm_stats.get("visible_node_history", []),
                        "growth_rounds": warm_stats.get("growth_rounds", 0),
                        "comment_open_attempts": warm_stats.get("comment_open_attempts", 0),
                        "comment_open_clicks": warm_stats.get("comment_open_clicks", 0),
                        "comment_panel_seen": warm_stats.get("comment_panel_seen", False),
                        "stop_reason": warm_stats.get("stop_reason", ""),
                        "comment_page_state": page_state.get("page_state", "normal"),
                        "comment_error_code": page_state.get("error_code", ""),
                        "comment_container_count": page_state.get("comment_container_count", 0),
                        "login_prompt_detected": page_state.get("login_prompt_detected", False),
                        "captcha_detected": page_state.get("captcha_detected", False),
                        "proxy_failure_detected": page_state.get("proxy_failure_detected", False),
                        "target_limit": limit,
                        "language": language,
                        "profile_completed": profile_completed,
                    },
                }
            )
        return comments

    def _inspect_comment_state(self, driver, warm_stats: dict) -> dict:
        diagnostics = {
            "page_state": "normal",
            "error_code": "",
            "stop_reason": warm_stats.get("stop_reason", ""),
            "scroll_rounds": warm_stats.get("scroll_rounds", 0),
            "stable_rounds": warm_stats.get("stable_rounds", 0),
            "max_visible_nodes": warm_stats.get("max_visible_nodes", 0),
            "comment_open_attempts": warm_stats.get("comment_open_attempts", 0),
            "comment_open_clicks": warm_stats.get("comment_open_clicks", 0),
            "comment_panel_seen": warm_stats.get("comment_panel_seen", False),
            "comment_container_count": 0,
            "login_prompt_detected": False,
            "captcha_detected": False,
            "proxy_failure_detected": False,
            "empty_comment_hint": False,
        }
        try:
            state = driver.execute_script(
                """
                const text = (document.body && document.body.innerText || '').toLowerCase();
                const title = (document.title || '').toLowerCase();
                const url = location.href || '';
                const pumbaaCtx = String(document.querySelector('meta[name="pumbaa-ctx"]')?.getAttribute('content') || '').toLowerCase();
                const loginStaticAsset = Array.from(document.querySelectorAll('script[src], link[href]')).some((node) => {
                  const value = String(node.getAttribute('src') || node.getAttribute('href') || '').toLowerCase();
                  return /website-login|tiktok_web_login_static/.test(value);
                });
                const commentNodes = document.querySelectorAll("[data-e2e*='comment'], [class*='Comment'], div[class*='comment'], [data-e2e*='reply']").length;
                const loginPrompt = /(log in to|sign up for|sign up \\| tiktok|log in to comment|log in to view comments|登录后|登入後|entrar para|iniciar sesión para)/.test(text + ' ' + title);
                const loginPage = /(^|\\|\\s*)sign up(\\s*\\||$)|login|log in/.test(title) || /\\/login|\\/signup/.test(url);
                const accountSetupGate =
                  (/login=1/.test(pumbaaCtx) || loginStaticAsset) &&
                  /(got it|how face or voice data is used|important things to know|location services|allow cookies from tiktok|privacy policy|terms of service)/.test(text + ' ' + title);
                const loginDialog = Array.from(document.querySelectorAll('[role="dialog"], [data-e2e*="modal"], div')).some((node) => {
                  try {
                    const value = String(node.innerText || '').toLowerCase();
                    const rect = node.getBoundingClientRect();
                    return rect.width > 240 && rect.height > 160 &&
                      /(log in to|sign up for|登录后|登入後|entrar para|iniciar sesión para)/.test(value);
                  } catch (e) { return false; }
                });
                const captcha = /captcha|verify|verification|验证|验证码|security check/.test(text);
                const proxy = /proxy|network error|no internet|err_tunnel|err_proxy|dns_probe|site can't be reached|无法访问/.test(text);
                const emptyHint = /no comments|be the first to comment|comments are turned off|暂无评论|sem comentários/.test(text);
                const containers = Array.from(document.querySelectorAll('div, section, aside, main')).filter((node) => {
                  try {
                    const nodeText = (node.innerText || '').toLowerCase();
                    return node.scrollHeight > node.clientHeight + 120 &&
                      (nodeText.includes('comment') || nodeText.includes('coment') || node.querySelector("[data-e2e*='comment']"));
                  } catch (e) { return false; }
                }).length;
                return {url, title, commentNodes, loginPrompt, loginPage, accountSetupGate, loginDialog, captcha, proxy, emptyHint, containers};
                """
            ) or {}
            diagnostics.update(
                {
                    "final_url": str(state.get("url") or getattr(driver, "current_url", "") or ""),
                    "page_title": str(state.get("title") or getattr(driver, "title", "") or "")[:160],
                    "visible_node_count": int(state.get("commentNodes") or 0),
                    "comment_container_count": int(state.get("containers") or 0),
                    "login_prompt_detected": bool(state.get("loginPrompt") or state.get("loginPage") or state.get("accountSetupGate")),
                    "account_setup_gate_detected": bool(state.get("accountSetupGate")),
                    "login_dialog_detected": bool(state.get("loginDialog")),
                    "captcha_detected": bool(state.get("captcha")),
                    "proxy_failure_detected": bool(state.get("proxy")),
                    "empty_comment_hint": bool(state.get("emptyHint")),
                }
            )
        except Exception as exc:
            diagnostics["inspect_error"] = f"{type(exc).__name__}: {exc}"
        if diagnostics["captcha_detected"]:
            diagnostics["page_state"] = "captcha"
            diagnostics["error_code"] = "CAPTCHA_DETECTED"
        elif diagnostics["proxy_failure_detected"]:
            diagnostics["page_state"] = "proxy_failed"
            diagnostics["error_code"] = "PROXY_FAILED"
        elif (diagnostics["login_prompt_detected"] or diagnostics.get("login_dialog_detected")) and int(diagnostics.get("max_visible_nodes") or 0) == 0:
            diagnostics["page_state"] = "login_required"
            diagnostics["error_code"] = "LOGIN_REQUIRED"
        elif diagnostics["empty_comment_hint"] or int(diagnostics.get("max_visible_nodes") or 0) == 0:
            diagnostics["page_state"] = "empty_comments"
            diagnostics["error_code"] = "COMMENT_SCAN_EMPTY"
        return diagnostics

    def _warm_comments(self, driver, limit: int):
        rounds = min(12, max(4, limit // 6 + 2))
        stable_rounds = 0
        previous_count = -1
        max_visible_nodes = 0
        executed_rounds = 0
        visible_node_history = []
        growth_rounds = 0
        max_comment_open_attempts = 0
        max_comment_open_clicks = 0
        comment_panel_seen = False
        for index in range(rounds):
            executed_rounds = index + 1
            try:
                open_stats = driver.execute_script(
                    """
                    function visible(node) {
                      try {
                        const rect = node.getBoundingClientRect();
                        return rect.width > 10 && rect.height > 10 && rect.bottom > 0 && rect.right > 0 &&
                          rect.top < (window.innerHeight || 900) && rect.left < (window.innerWidth || 1400);
                      } catch (e) { return false; }
                    }
                    function point(node) {
                      try {
                        const rect = node.getBoundingClientRect();
                        return {
                          x: Math.max(1, Math.min((window.innerWidth || 1400) - 1, rect.left + rect.width / 2)),
                          y: Math.max(1, Math.min((window.innerHeight || 900) - 1, rect.top + rect.height / 2))
                        };
                      } catch (e) {
                        return {x: 1, y: 1};
                      }
                    }
                    function clickNode(node) {
                      if (!node) return false;
                      const p = point(node);
                      try {
                        node.scrollIntoView({block: 'center', inline: 'center'});
                      } catch (e) {}
                      try { node.click(); return true; } catch (e) {}
                      try {
                        const events = ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
                        for (const name of events) {
                          const Ctor = name.startsWith('pointer') && window.PointerEvent ? PointerEvent : MouseEvent;
                          node.dispatchEvent(new Ctor(name, {bubbles: true, cancelable: true, view: window, clientX: p.x, clientY: p.y}));
                        }
                        return true;
                      } catch (e) {}
                      return false;
                    }
                    function commentPanelVisible() {
                      const roots = document.querySelectorAll(
                        '[data-e2e*="comment-level"], [data-e2e*="comment-item"], [data-e2e*="comment-list"], div[class*="CommentItem"], div[class*="DivCommentItem"]'
                      );
                      if (roots.length > 0) return true;
                      const text = (document.body && document.body.innerText || '').toLowerCase();
                      return /(add comment|write a comment|view replies|reply|replies|responder|ver respostas|no comments|be the first to comment)/.test(text);
                    }
                    function clickableAncestor(node) {
                      let item = node;
                      for (let depth = 0; item && depth < 6; depth++) {
                        const role = String(item.getAttribute && item.getAttribute('role') || '').toLowerCase();
                        const tag = String(item.tagName || '').toLowerCase();
                        if (tag === 'button' || tag === 'a' || role === 'button') return item;
                        item = item.parentElement;
                      }
                      return node;
                    }
                    let attempted = 0;
                    let clicked = 0;
                    const directTargets = Array.from(document.querySelectorAll(
                      '[data-e2e*="comment"], button[aria-label*="comment" i], [role="button"][aria-label*="comment" i], [aria-label*="comment" i], button[aria-label*="coment" i], [role="button"][aria-label*="coment" i], [aria-label*="coment" i]'
                    )).filter(visible);
                    for (const node of directTargets.slice(0, 20)) {
                      const text = (node.innerText || node.getAttribute('aria-label') || node.getAttribute('data-e2e') || '').toLowerCase();
                      if (text.includes('comment') || text.includes('coment')) {
                        attempted += 1;
                        if (clickNode(clickableAncestor(node))) clicked += 1;
                      }
                    }
                    const width = window.innerWidth || 1400;
                    const height = window.innerHeight || 900;
                    const railCandidates = Array.from(document.querySelectorAll('button, [role="button"], div'))
                      .filter(visible)
                      .map((node) => {
                        const rect = node.getBoundingClientRect();
                        const text = (node.innerText || node.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim();
                        return {node, rect, text};
                      })
                      .filter((item) => {
                        const numeric = /^\\d+(\\.\\d+)?\\s*([KMB万億亿])?$/i.test(item.text);
                        const rightRail = item.rect.left > width * 0.62;
                        const midLower = item.rect.top > height * 0.42 && item.rect.top < height * 0.86;
                        return rightRail && midLower && (numeric || /comment|coment/i.test(item.text));
                      })
                      .sort((a, b) => {
                        const targetY = height * 0.66;
                        return Math.abs((a.rect.top + a.rect.bottom) / 2 - targetY) - Math.abs((b.rect.top + b.rect.bottom) / 2 - targetY);
                      });
                    for (const item of railCandidates.slice(0, 2)) {
                      attempted += 1;
                      if (clickNode(clickableAncestor(item.node))) clicked += 1;
                    }
                    const coordinateAttempts = [
                      [0.795, 0.675],
                      [0.80, 0.66],
                      [0.80, 0.62],
                      [0.82, 0.68],
                      [0.78, 0.66],
                      [0.86, 0.66]
                    ];
                    for (const [xRatio, yRatio] of coordinateAttempts) {
                      const target = document.elementFromPoint(width * xRatio, height * yRatio);
                      if (target) {
                        const node = clickableAncestor(target);
                        attempted += 1;
                        if (clickNode(node)) clicked += 1;
                      }
                    }
                    return {
                      attempted,
                      clicked,
                      direct_target_count: directTargets.length,
                      rail_candidate_count: railCandidates.length,
                      panel_visible: commentPanelVisible()
                    };
                    """
                ) or {}
                if isinstance(open_stats, dict):
                    max_comment_open_attempts = max(max_comment_open_attempts, int(open_stats.get("attempted") or 0))
                    max_comment_open_clicks = max(max_comment_open_clicks, int(open_stats.get("clicked") or 0))
                    comment_panel_seen = comment_panel_seen or bool(open_stats.get("panel_visible"))
                count = int(
                    driver.execute_script(
                        "return document.querySelectorAll(\"[data-e2e*='comment'], [class*='Comment'], div[class*='comment'], [data-e2e*='reply']\").length"
                    )
                    or 0
                )
                visible_node_history.append(count)
                if previous_count >= 0 and count > previous_count:
                    growth_rounds += 1
                max_visible_nodes = max(max_visible_nodes, count)
                if count >= limit:
                    return {
                        "scroll_rounds": executed_rounds,
                        "stable_rounds": stable_rounds,
                        "max_visible_nodes": max_visible_nodes,
                        "visible_node_history": visible_node_history,
                        "growth_rounds": growth_rounds,
                        "comment_open_attempts": max_comment_open_attempts,
                        "comment_open_clicks": max_comment_open_clicks,
                        "comment_panel_seen": comment_panel_seen,
                        "stop_reason": "limit_reached",
                    }
                if count == previous_count:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                previous_count = count
                driver.execute_script(
                    """
                    window.scrollBy(0, Math.max(500, window.innerHeight || 600));
                    const containers = Array.from(document.querySelectorAll('div, section, aside, main')).slice(0, 260)
                      .filter((node) => {
                        try {
                          const text = (node.innerText || '').toLowerCase();
                          return node.scrollHeight > node.clientHeight + 120 &&
                            (text.includes('comment') || text.includes('coment') || text.includes('responder') || node.querySelector('[data-e2e*="comment"]'));
                        } catch (e) { return false; }
                      });
                    for (const node of containers) {
                      try {
                        if (node.scrollHeight > node.clientHeight + 120) {
                          node.scrollTop = Math.min(node.scrollHeight, node.scrollTop + Math.max(500, node.clientHeight || 500));
                        }
                      } catch (e) {}
                    }
                    try { window.dispatchEvent(new KeyboardEvent('keydown', {key: 'PageDown'})); } catch (e) {}
                    """
                )
                if stable_rounds >= 2 and count > 0:
                    return {
                        "scroll_rounds": executed_rounds,
                        "stable_rounds": stable_rounds,
                        "max_visible_nodes": max_visible_nodes,
                        "visible_node_history": visible_node_history,
                        "growth_rounds": growth_rounds,
                        "comment_open_attempts": max_comment_open_attempts,
                        "comment_open_clicks": max_comment_open_clicks,
                        "comment_panel_seen": comment_panel_seen,
                        "stop_reason": "stable_with_comments",
                    }
            except Exception:
                pass
            time.sleep(1.5)
        return {
            "scroll_rounds": executed_rounds,
            "stable_rounds": stable_rounds,
            "max_visible_nodes": max_visible_nodes,
            "visible_node_history": visible_node_history,
            "growth_rounds": growth_rounds,
            "comment_open_attempts": max_comment_open_attempts,
            "comment_open_clicks": max_comment_open_clicks,
            "comment_panel_seen": comment_panel_seen,
            "stop_reason": "round_limit",
        }
