"""Browser adapter: live UI observations, strict targeting and network containment."""

import json
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from cua.core.schemas import Condition, Step, Target
from cua.execution.policy import Policy, PolicyViolation


class SurfaceError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class BrowserSurface:
    def __init__(self, policy: Policy, evidence, *, headed=False, slow_mo=0):
        self.policy = policy
        self.evidence = evidence
        self.headed = headed
        self.slow_mo = slow_mo
        self.owner = "AUTOMATION"
        self.blocked = None
        self.catalog: dict[str, Target] = {}

    def __enter__(self):
        self.playwright = sync_playwright().start()
        try:
            self.browser = self.playwright.chromium.launch(
                headless=not self.headed, slow_mo=self.slow_mo
            )
            self.context = self.browser.new_context(accept_downloads=False, service_workers="block")
            self.context.route("**/*", self._route)
            self.context.expose_binding("__cuaManualEvent", self._manual_event)
            self.context.add_init_script("""(() => {
              for (const kind of ['click','change','submit']) {
                document.addEventListener(kind, e => {
                  window.__cuaManualEvent({kind, tag: e.target.tagName.toLowerCase(),
                    input_type: e.target.type || '',
                    control: ['BUTTON','A'].includes(e.target.tagName)
                      ? (e.target.innerText || '').trim().replace(/\\s+/g,' ') : ''
                  }).catch(() => {});
                }, true);
              }
            })();""")
            self.page = self.context.new_page()
            self.page.on("dialog", self._native_dialog)
            self.context.on("page", self._popup)
            self.page.set_default_timeout(4000)
            return self
        except Exception:
            self.playwright.stop()
            raise

    def __exit__(self, *args):
        self.browser.close()
        self.playwright.stop()

    def _route(self, route):
        request = route.request
        try:
            self.policy.check_url(request.url)
            if request.method != "GET":
                manual_login = (
                    self.owner == "HUMAN"
                    and request.method == "POST"
                    and urlsplit(request.url).path == "/restore-session"
                )
                if not manual_login:
                    raise PolicyViolation("METHOD_BLOCKED")
            # Playwright interception is not guaranteed to run again for each redirect.
            # Forward only this browser-initiated request, inspect before giving it back
            # to Chromium, and conservatively reject server redirects in this adapter.
            response = route.fetch(max_redirects=0, max_retries=0, timeout=10000)
            if 300 <= response.status < 400 and response.headers.get("location"):
                self.policy.check_url(urljoin(request.url, response.headers["location"]))
                raise PolicyViolation("REDIRECT_BLOCKED")
            route.fulfill(response=response)
        except PolicyViolation as exc:
            self.blocked = str(exc)
            route.abort()
        except Exception:
            self.blocked = "NETWORK_ERROR"
            route.abort()

    def _popup(self, page):
        self.blocked = "POPUP_BLOCKED"
        page.close()

    def _native_dialog(self, dialog):
        # Cancel unrecognized native confirmations and stop, never auto-accept.
        self.blocked = "NATIVE_DIALOG_BLOCKED"
        dialog.dismiss()

    def _manual_event(self, source, event):
        if self.owner == "HUMAN":
            # Never persist text, input values, attributes or coordinates.
            self.evidence.event(
                "human_action",
                control=event.get("control")
                if event.get("control") in self.policy.human_control_names
                else "[REDACTED]",
                action=event.get("kind")
                if event.get("kind") in ("click", "change", "submit")
                else "unknown",
                tag=event.get("tag")
                if event.get("tag") in ("a", "button", "input", "form", "select", "option")
                else "other",
                input_type=event.get("input_type")
                if event.get("input_type")
                in ("text", "password", "submit", "button", "checkbox", "radio")
                else "other",
            )

    def set_owner(self, owner: str):
        self.owner = owner
        self.evidence.event("ownership_changed", owner=owner)

    def assert_allowed(self):
        if self.blocked:
            raise PolicyViolation(self.blocked)
        for frame in self.page.frames:
            if frame.url not in ("", "about:blank"):
                self.policy.check_url(frame.url)

    def navigate(self, url: str):
        self.policy.check_url(url)
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except Exception:
            self.assert_allowed()
            raise
        self.assert_allowed()
        version = self.page.locator('meta[name="app-version"]').get_attribute("content")
        if version != "1":
            raise SurfaceError("APP_VERSION_MISMATCH")

    def locator(self, target: Target):
        root = self.page.frame_locator(target.frame) if target.frame else self.page
        if target.kind == "role":
            return root.get_by_role(target.role, name=target.value, exact=True)
        if target.kind == "label":
            return root.get_by_label(target.value, exact=True)
        if target.kind == "text":
            return root.get_by_text(target.value, exact=True)
        return root.locator(target.value)

    def visible(self, target: Target) -> bool:
        locator = self.locator(target)
        return locator.count() == 1 and locator.is_visible()

    def _unique(self, target: Target, timeout: int):
        locator = self.locator(target)
        if locator.count() > 1:
            raise SurfaceError("AMBIGUOUS_TARGET")
        try:
            locator.wait_for(state="visible", timeout=timeout)
        except PlaywrightTimeout as exc:
            raise SurfaceError("TARGET_TIMEOUT") from exc
        if locator.count() != 1:
            raise SurfaceError("AMBIGUOUS_TARGET")
        return locator

    def execute(self, step: Step, inputs: dict[str, str]) -> str | None:
        if self.owner != "AUTOMATION":
            raise SurfaceError("AUTOMATION_NOT_OWNER")
        self.assert_allowed()
        locator = self._unique(step.target, step.timeout_ms)
        name = locator.evaluate("""e => (e.getAttribute('aria-label') ||
          (e.labels && e.labels.length ? e.labels[0].innerText : e.innerText) || '').trim()
          .replace(/\\s+/g, ' ')""")
        self.policy.check_action(step.action, name)
        if step.action == "click":
            destination = locator.evaluate("e => e.href || (e.form && e.form.action) || null")
            if destination:
                self.policy.check_url(urljoin(self.page.url, destination))
            locator.click(timeout=step.timeout_ms)
        elif step.action == "fill":
            locator.fill(step.value.resolve(inputs), timeout=step.timeout_ms)
        elif step.action == "assert":
            if locator.inner_text().strip() != step.value.resolve(inputs):
                raise SurfaceError("CHECKPOINT_MISMATCH")
        elif step.action == "extract":
            return locator.inner_text().strip()
        self.assert_allowed()
        return None

    def check(self, condition: Condition, inputs: dict[str, str]):
        locator = self._unique(condition.target, 4000)
        if condition.test == "text_equals":
            if locator.inner_text().strip() != condition.value.resolve(inputs):
                raise SurfaceError("CHECKPOINT_MISMATCH")

    def _frames(self):
        yield self.page.main_frame, None
        for frame in self.page.frames:
            if frame == self.page.main_frame:
                continue
            element = frame.frame_element()
            title = element.get_attribute("title")
            name = element.get_attribute("name")
            selector = (
                f"iframe[title={json.dumps(title)}]"
                if title
                else f"iframe[name={json.dumps(name)}]"
                if name
                else None
            )
            # No guessing frame indices: unsupported frames require human intervention.
            if selector is None or frame.parent_frame != self.page.main_frame:
                raise SurfaceError("UNSUPPORTED_FRAME")
            yield frame, selector

    def observe(self) -> dict:
        self.assert_allowed()
        self.catalog = {}
        elements = []
        for frame, scope in self._frames():
            candidates = frame.evaluate("""() => {
              const rows = [];
              const controls = 'input:not([type=hidden]),button,a,h1,h2,td';
              for (const e of document.querySelectorAll(controls)) {
                if (!e.checkVisibility()) continue;
                const tag=e.tagName.toLowerCase();
                const label=e.labels?.[0]?.innerText?.trim();
                const text=(e.innerText||'').trim().replace(/\\s+/g,' ');
                if (e.closest('[data-sensitive]') && tag !== 'td') continue;
                if (tag==='input' && label) rows.push({kind:'label',value:label,role:null,
                  filled: e.value.length > 0});
                else if (tag==='button' || tag==='a') rows.push({kind:'role',
                  role:tag==='a'?'link':'button',value:text});
                else if (tag==='h1' || tag==='h2')
                  rows.push({kind:'role',role:'heading',value:text});
                else if (tag==='td') {
                  const th=e.parentElement.querySelector('th');
                  if(th && e.parentElement.querySelectorAll('td').length===1) {
                    rows.push({kind:'css',role:null,
                      value:'tr:has(> th:text-is('+JSON.stringify(th.innerText.trim())+')) > td',
                      field:th.innerText.trim()});
                  }
                }
              }
              return rows;
            }""")
            for item in candidates:
                field = item.pop("field", None)
                filled = item.pop("filled", None)
                target = Target(**item, frame=scope)
                if target.kind == "label":
                    candidates_for_action = ["fill"]
                elif target.role in ("button", "link"):
                    candidates_for_action = ["click"]
                elif target.role == "heading":
                    # Headings describe state; visibility checkpoints are recorded separately.
                    candidates_for_action = []
                else:
                    candidates_for_action = ["assert", "extract"]
                allowed_actions = []
                for action in candidates_for_action:
                    try:
                        self.policy.check_action(action, target.value)
                    except PolicyViolation:
                        continue
                    allowed_actions.append(action)
                ref = f"e{len(elements) + 1}"
                self.catalog[ref] = target
                elements.append(
                    {
                        "ref": ref,
                        "target": target.model_dump(),
                        "field": field,
                        "allowed_actions": allowed_actions,
                        "filled": filled,
                    }
                )
        return {"elements": elements, "path": urlsplit(self.page.url).path}

    def structural_snapshot(self):
        return [
            frame.evaluate("""() => {
          function shape(e) {
            return {tag:e.tagName.toLowerCase(), children:Array.from(e.children)
              .filter(c=>!['SCRIPT','STYLE'].includes(c.tagName)).map(shape)};
          }
          return shape(document.body);
        }""")
            for frame in self.page.frames
        ]
