/* Run in the real Analytics/Constraint WebView at 1024 x 720 after opening panels.
 * Returns measured failures; it does not mock CSS geometry or mutate application state.
 */
function checkWayriCADPanelLayout() {
  const failures = [], measurements = [];
  const visible = element => element.getClientRects().length > 0;
  for (const element of document.querySelectorAll('.table-wrap,.scope-scroll,.routing-net-list,.map-wrap')) {
    if (!visible(element)) continue;
    const style = getComputedStyle(element), bounds = element.getBoundingClientRect();
    const name = element.id || element.className;
    const minimumWidth = element.matches('.scope-scroll') ? 100 : 160;
    if (bounds.width < minimumWidth || bounds.height < 70) failures.push(name + ': unreadably small');
    if (!['vertical', 'both'].includes(style.resize)) failures.push(name + ': cannot resize');
    if (element.scrollHeight > element.clientHeight + 2 && !['auto','scroll'].includes(style.overflowY)) failures.push(name + ': vertical contents inaccessible');
    if (element.scrollWidth > element.clientWidth + 2 && !['auto','scroll'].includes(style.overflowX)) failures.push(name + ': horizontal contents inaccessible');
    const original = element.style.height;
    element.style.height = '480px';
    const enlarged = element.getBoundingClientRect().height;
    element.style.height = original;
    if (bounds.height < 400 && enlarged < 400) failures.push(name + ': surrounding layout prevents enlargement');
    measurements.push({name,width:bounds.width,height:bounds.height,enlargedHeight:enlarged});
  }
  const dialog = document.querySelector('dialog[open]');
  if (dialog) {
    const bounds = dialog.getBoundingClientRect();
    if (bounds.top < -1 || bounds.bottom > innerHeight + 1) failures.push('dialog extends beyond viewport');
    const body = dialog.querySelector('#dialogBody,#dialog-body');
    if (body && body.scrollHeight > body.clientHeight + 2 && getComputedStyle(body).overflowY !== 'auto') failures.push('dialog body cannot scroll');
    for (const control of dialog.querySelectorAll('.dialog-head button,.dialog-foot button')) {
      const rect = control.getBoundingClientRect();
      if (rect.top < bounds.top || rect.bottom > bounds.bottom + 1) failures.push('dialog action is clipped: ' + control.textContent.trim());
    }
  }
  const main = document.querySelector('main');
  if (main && main.getBoundingClientRect().right > innerWidth + 2) failures.push('workspace extends beyond viewport');
  return {viewport:[innerWidth,innerHeight],failures,measurements};
}
if (typeof module !== 'undefined') module.exports = {checkWayriCADPanelLayout};
