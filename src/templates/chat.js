// Chat page enhancement (ticket #5): on load, re-render each assistant message
// as sanitized markdown; on submit, show a pulse overlay until the full-page
// response replaces it. Progressive enhancement: with no JS the server-rendered
// escaped text remains as-is. User messages are never markdown-parsed.
(function () {
  function renderAssistant() {
    var hidden = document.querySelector('form.say input[name="transcript"]');
    var msgs = document.querySelectorAll('.msg.assistant');
    if (!hidden || !msgs.length) return;
    var transcript;
    try { transcript = JSON.parse(hidden.value); } catch (e) { return; }
    // Assistant messages are a filtered subset of the transcript; index the
    // filtered list so entry i lines up with the i-th .msg.assistant on page.
    var replies = transcript.filter(function (m) {
      if (!m || m.role !== 'assistant' || typeof m.content !== 'string') return false;
      // Assistant rows holding a tool-call JSON blob render no bubble
      // server-side (chips stand in); never markdown-render them here.
      try {
        var d = JSON.parse(m.content);
        if (d && typeof d === 'object' && d.tool_calls) return false;
      } catch (e) { /* plain text, fine */ }
      return true;
    });
    msgs.forEach(function (el, i) {
      var msg = replies[i];
      if (!msg) return;
      // Source is the transcript JSON, never the DOM, and sanitize:
      // model output is untrusted.
      el.innerHTML = '<strong>BoldTrader</strong>' +
        DOMPurify.sanitize(marked.parse(msg.content));
      el.classList.add('rendered');
    });
  }
  document.addEventListener('DOMContentLoaded', function () {
    if (window.marked && window.DOMPurify) renderAssistant();
    var form = document.querySelector('form.say');
    if (form) form.addEventListener('submit', function () {
      var ov = document.getElementById('overlay');
      if (ov) ov.classList.add('show');
    });
  });
})();
