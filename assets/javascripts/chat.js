/**
 * Merlya Docs Chat Widget
 * Floating chat button that connects to RAG API
 */

(function() {
  'use strict';

  const RAG_API_URL =
    (typeof window !== 'undefined' && window.__MERLYA_RAG_API_URL) ||
    'https://merlya-rag.cold-bar-16e7.workers.dev/ask';

  // Create chat widget HTML
  function createChatWidget() {
    const widget = document.createElement('div');
    widget.id = 'merlya-chat-widget';
    widget.innerHTML = `
      <button id="chat-toggle" aria-label="Open chat">
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
      </button>
      <div id="chat-panel" class="hidden">
        <div id="chat-header">
          <span>Ask Merlya</span>
          <button id="chat-close" aria-label="Close chat">&times;</button>
        </div>
        <div id="chat-messages">
          <div class="message bot">
            Hi! I can help you with questions about Merlya. What would you like to know?
          </div>
        </div>
        <form id="chat-form">
          <input type="text" id="chat-input" placeholder="Ask a question..." autocomplete="off" maxlength="500">
          <button type="submit" id="chat-send" aria-label="Send">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          </button>
        </form>
      </div>
    `;
    document.body.appendChild(widget);
  }

  // Initialize chat functionality
  function initChat() {
    const toggle = document.getElementById('chat-toggle');
    const panel = document.getElementById('chat-panel');
    const closeBtn = document.getElementById('chat-close');
    const form = document.getElementById('chat-form');
    const input = document.getElementById('chat-input');
    const messages = document.getElementById('chat-messages');

    // Toggle panel
    toggle.addEventListener('click', () => {
      panel.classList.toggle('hidden');
      if (!panel.classList.contains('hidden')) {
        input.focus();
      }
    });

    // Close panel
    closeBtn.addEventListener('click', () => {
      panel.classList.add('hidden');
    });

    // Handle form submission
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const question = input.value.trim();
      if (!question) return;

      // Add user message
      addMessage(question, 'user');
      input.value = '';
      input.disabled = true;

      // Show loading
      const loadingId = addMessage('Thinking...', 'bot loading');

      try {
        const response = await fetch(RAG_API_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question })
        });

        // Remove loading message
        const loadingEl = document.getElementById(loadingId);
        if (loadingEl) loadingEl.remove();

        if (!response.ok) {
          // Try to parse error response safely
          let errorMessage = 'Sorry, I encountered an error. Please try again later.';
          try {
            const errorData = await response.json();
            if (errorData.error) {
              errorMessage = errorData.error;
            } else if (errorData.message) {
              errorMessage = errorData.message;
            }
          } catch (parseErr) {
            // If JSON parsing fails, use generic message
            errorMessage = `Request failed with status ${response.status}. Please try again later.`;
          }
          addMessage(errorMessage, 'bot error');
        } else {
          // Parse successful response
          const data = await response.json();
          if (data.error) {
            addMessage('Sorry, I encountered an error. Please try again later.', 'bot error');
          } else {
            addMessage(data.answer, 'bot');
          }
        }
      } catch (err) {
        // Remove loading message
        const loadingEl = document.getElementById(loadingId);
        if (loadingEl) loadingEl.remove();
        addMessage('Unable to connect. Please check your connection and try again.', 'bot error');
      } finally {
        input.disabled = false;
        input.focus();
      }
    });

    // Close on Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !panel.classList.contains('hidden')) {
        panel.classList.add('hidden');
      }
    });
  }

  // Add message to chat
  function addMessage(text, className) {
    const messages = document.getElementById('chat-messages');
    const id = 'msg-' + Date.now();
    const div = document.createElement('div');
    div.id = id;
    div.className = 'message ' + className;
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return id;
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      createChatWidget();
      initChat();
    });
  } else {
    createChatWidget();
    initChat();
  }
})();
