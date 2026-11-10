# Design

## Source of truth
Status: Active. Date: 2026-11-10. Surfaces: public home, auth, dashboard, device setup/map on iPhone. Evidence: current Flask templates, mobile screenshot, WLOC interaction requirements.

## Brand
“闪现啦” should feel precise, calm, fast, and trustworthy. Use the lightning/location mark as the primary brand signal. Avoid hacker-tool aesthetics, dense configuration screens, neon gradients, and unexplained technical jargon.

## Product goals
- Help a non-technical user complete setup and choose a location.
- Make device state and next action obvious.
- Preserve a clear boundary between server-saved coordinates and device-side execution.
- Non-goal: hide iOS security confirmations or claim guaranteed location success.

## Personas and jobs
- Consumer: open a device link, complete setup, choose/search/save a location.
- Operator: sign in, create an order/device, issue a guided setup link.

## Information architecture
Public home → register/login → dashboard → device setup → guided install / map / saved places / active device state.

## Design principles
1. One primary action per state.
2. Progressive disclosure: setup details appear when needed.
3. Technical terms are paired with plain-language explanation.
4. Mobile-first touch targets of at least 44px.
5. Show uncertainty honestly: “已写入设备配置” is not “系统定位已生效”.

## Visual language
- Background: cool off-white `#f5f7fb`; surfaces white; primary ink `#14213d`.
- Accent: electric blue `#3267f5`; violet only in the logo gradient.
- Typography: system sans stack, 14–16px body, compact 1.5 line-height.
- Shape: 16px cards, 10–12px controls, low diffuse shadows.
- Avoid heavy borders; use soft surface separation and one primary blue action.

## Components
Brand header, hero panel, auth card, stat/card surfaces, primary/secondary/danger buttons, map layer controls, favorite rows, setup steps, status/alert banners.

## Accessibility
Use semantic buttons/labels, visible focus rings, sufficient contrast, keyboard access on desktop, and text alternatives for the logo. Do not rely on color alone for state.

## Responsive behavior
Desktop uses a centered max-width shell and two-column dashboard. Mobile collapses to one column, keeps actions full-width or wrapped, uses a 52–58vh map, and keeps the layer switcher and save action reachable.

## Interaction states
Support loading, empty favorites, success, error, disabled, and slow/offline map/search states. Preserve entered coordinates when a remote request fails.

## Content voice
Chinese, concise, reassuring, action-led. Prefer “导入模块”“开启证书信任”“已保存到服务器” over raw protocol terminology.

## Implementation constraints
Flask/Jinja templates and existing Leaflet remain. Keep external map providers out of the primary user flow where possible; use the existing Flask tile/geocode proxy. Tokens remain server-side and are never printed as upstream module URLs.

## Open questions
- [ ] Choose production payment provider and operator/admin workflow; owner: product; impact: checkout and order states.
- [ ] Add real device diagnostics/heartbeat; owner: engineering; impact: setup completion confidence.
