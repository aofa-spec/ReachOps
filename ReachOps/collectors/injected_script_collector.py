# -*- coding: utf-8 -*-
from __future__ import annotations

from .base import CollectorAdapter


class InjectedScriptCollector(CollectorAdapter):
    """Content-script style collector using a single injected JavaScript block."""

    level = "injected_script"

    def __init__(self, script: str, normalizer=None):
        self.script = script
        self.normalizer = normalizer or (lambda rows, task, context: rows or [])

    def collect(self, driver, task, context):
        rows = driver.execute_script(self.script)
        return self.normalizer(rows or [], task, context)


TIKTOK_VIDEO_LINK_SCRIPT = """
const anchors = Array.from(document.querySelectorAll('a[href*="/video/"]'));
const seen = new Set();
const out = [];
for (const a of anchors) {
  const href = a.href || a.getAttribute('href') || '';
  if (!href || seen.has(href)) continue;
  seen.add(href);
  const card = a.closest('[data-e2e], article, div') || a;
  const text = (card.innerText || a.innerText || '').trim();
  const img = card.querySelector('img');
  out.push({
    href,
    text,
    caption: (a.getAttribute('title') || (img && img.alt) || text || '').trim()
  });
}
return out;
"""


TIKTOK_COMMENT_SCRIPT = """
const out = [];
const seen = new Set();
function textOf(node) {
  return String((node && (node.innerText || node.textContent)) || '').replace(/\\s+/g, ' ').trim();
}
function cleanLines(text) {
  return String(text || '')
    .split(/\\n+/)
    .map((line) => line.replace(/\\s+/g, ' ').trim())
    .filter((line) => line && !/^(follow|following|seguir|seguindo|responder|reply|view replies?|ver respostas?|like|share)$/i.test(line));
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
function boundedCommentBlock(link) {
  let node = link;
  for (let depth = 0; node && depth < 8; depth++) {
    const text = textOf(node);
    const links = node.querySelectorAll ? node.querySelectorAll('a[href*="/@"]').length : 0;
    const interactionText = /reply|replies|responder|respostas?|respuesta|ver respostas?|view replies?|like/i.test(text);
    if (text.length >= 8 && text.length <= 900 && links <= 3 && (hasCommentMarker(node) || interactionText)) {
      return node;
    }
    node = node.parentElement;
  }
  return null;
}
const strictRoots = Array.from(document.querySelectorAll(
  '[data-e2e*="comment-level"], [data-e2e*="comment-item"], [data-e2e*="comment-list"] [role="listitem"], div[class*="CommentItem"], div[class*="DivCommentItem"]'
));
const strictLinks = strictRoots.flatMap((node) => Array.from(node.querySelectorAll('a[href*="/@"]')));
const profileLinks = strictLinks.length
  ? strictLinks
  : Array.from(document.querySelectorAll('a[href*="/@"]')).filter((link) => Boolean(boundedCommentBlock(link)));
for (let i = 0; i < profileLinks.length; i++) {
  const link = profileLinks[i];
  const usernameFromHref = link ? (link.href.split('/@').pop().split(/[/?#]/)[0]) : '';
  const username = link ? ((link.innerText || usernameFromHref || '').trim()) : usernameFromHref;
  const node = boundedCommentBlock(link);
  if (!node) continue;
  const lines = cleanLines(node.innerText || '');
  const usernameLower = String(username || '').toLowerCase();
  const text = (lines
    .filter((line) => line.toLowerCase() !== usernameLower && !line.toLowerCase().includes('@' + usernameLower))
    .sort((a, b) => b.length - a.length)[0] || '').trim();
  const key = `${username}|${text}`;
  if (!username || !text || seen.has(key)) continue;
  seen.add(key);
  out.push({
    username,
    profile_url: link ? link.href : '',
    comment_text: text,
    node_index: i,
    visible_node_count: profileLinks.length,
    max_visible_nodes: profileLinks.length,
    node_text_length: (node.innerText || '').length
  });
}
return out;
"""
