import { useState, useCallback, useRef, useEffect } from 'react';

export interface ChatMessage {
  id: string;
  type: 'user' | 'agent';
  thinking?: string;
  result: string;
  timestamp: string;
  vertical?: string;
  vmo_meta?: any;
}

export interface DualColumnMessage {
  id: string;
  userMessage: ChatMessage;
  withDbResponse?: ChatMessage;
  independentResponse?: ChatMessage;
}

export interface UseCompassChatReturn {
  messages: ChatMessage[];
  dualMessages: DualColumnMessage[];
  isLoading: boolean;
  error: string | null;
  sendMessage: (query: string, vertical: string) => Promise<void>;
  sendDualMessage: (query: string, vertical: string) => Promise<void>;
  clearMessages: () => void;
  removeMessage: (id: string) => void;
}

const COMPASS_CHAT_STORAGE_KEY = 'compass_chat_messages';
const COMPASS_DUAL_CHAT_STORAGE_KEY = 'compass_dual_chat_messages';
const COMPASS_MESSAGE_COUNT_KEY = 'compass_message_count';

// Module-level state survives component unmount/remount
let activeRequestCount = 0;
const pendingResponses = new Map<string, { withDb?: ChatMessage; independent?: ChatMessage }>();

// Helper to persist to localStorage
function saveDualMessages(messages: DualColumnMessage[]) {
  try {
    localStorage.setItem(COMPASS_DUAL_CHAT_STORAGE_KEY, JSON.stringify(messages));
  } catch (e) {
    console.error('Failed to save messages:', e);
  }
}

// On mount, merge any pending responses that arrived while component was unmounted
function hydrateDualMessages(): DualColumnMessage[] {
  try {
    const stored = localStorage.getItem(COMPASS_DUAL_CHAT_STORAGE_KEY);
    if (!stored) return [];
    
    const parsed: DualColumnMessage[] = JSON.parse(stored);
    
    // Merge in any responses that completed while unmounted
    return parsed.map((msg) => {
      const pending = pendingResponses.get(msg.id);
      if (pending) {
        const updated = {
          ...msg,
          withDbResponse: pending.withDb ?? msg.withDbResponse,
          independentResponse: pending.independent ?? msg.independentResponse,
        };
        // Clear from pending cache once merged
        if (pending.withDb && pending.independent) {
          pendingResponses.delete(msg.id);
        }
        return updated;
      }
      return msg;
    });
  } catch {
    return [];
  }
}

export const useCompassChat = (): UseCompassChatReturn => {
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    if (typeof window === 'undefined') return [];
    const stored = localStorage.getItem(COMPASS_CHAT_STORAGE_KEY);
    return stored ? JSON.parse(stored) : [];
  });

  const [dualMessages, setDualMessages] = useState<DualColumnMessage[]>(() => {
    if (typeof window === 'undefined') return [];
    return hydrateDualMessages();
  });

  const [isLoading, setIsLoading] = useState(() => activeRequestCount > 0);
  const [error, setError] = useState<string | null>(null);
  const messageCountRef = useRef(0);
  const isMountedRef = useRef(true);

  // On mount, check for any pending responses that completed while unmounted
  useEffect(() => {
    isMountedRef.current = true;
    
    // Merge any cached responses immediately
    const checkPendingResponses = () => {
      if (pendingResponses.size > 0) {
        setDualMessages((prev) => {
          let hasChanges = false;
          const updated = prev.map((msg) => {
            const cached = pendingResponses.get(msg.id);
            if (cached) {
              const needsUpdate = 
                (cached.withDb && !msg.withDbResponse) || 
                (cached.independent && !msg.independentResponse);
              
              if (needsUpdate) {
                hasChanges = true;
                return {
                  ...msg,
                  withDbResponse: cached.withDb ?? msg.withDbResponse,
                  independentResponse: cached.independent ?? msg.independentResponse,
                };
              }
            }
            return msg;
          });
          
          if (hasChanges) {
            saveDualMessages(updated);
            return updated;
          }
          return prev;
        });
      }
    };

    // Check immediately on mount
    checkPendingResponses();

    // Poll every 500ms while there are pending responses
    const interval = setInterval(() => {
      if (pendingResponses.size > 0) {
        checkPendingResponses();
      }
    }, 500);

    return () => {
      isMountedRef.current = false;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem(COMPASS_MESSAGE_COUNT_KEY);
      messageCountRef.current = stored ? parseInt(stored, 10) : 0;
    }
  }, []);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem(COMPASS_CHAT_STORAGE_KEY, JSON.stringify(messages));
    }
  }, [messages]);

  useEffect(() => {
    saveDualMessages(dualMessages);
  }, [dualMessages]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem(COMPASS_MESSAGE_COUNT_KEY, messageCountRef.current.toString());
    }
  });

  const startLoading = () => {
    activeRequestCount++;
    setIsLoading(true);
  };

  const stopLoading = () => {
    activeRequestCount = Math.max(0, activeRequestCount - 1);
    if (activeRequestCount === 0) setIsLoading(false);
  };

  const sendMessage = useCallback(async (query: string, vertical: string) => {
    if (!query.trim() || !vertical) {
      setError('Query and vertical are required');
      return;
    }

    const messageId = `msg-${++messageCountRef.current}`;
    startLoading();
    setError(null);

    try {
      const userMessage: ChatMessage = {
        id: `user-${messageId}`,
        type: 'user',
        result: query,
        timestamp: new Date().toISOString(),
        vertical,
      };
      setMessages((prev) => [...prev, userMessage]);

      const response = await fetch('/api/chat/compass', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, vertical, temperature: 0.7, max_tokens: 2000 }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      const agentMessage: ChatMessage = {
        id: `agent-${messageId}`,
        type: 'agent',
        thinking: data.thinking,
        result: data.result,
        vmo_meta: data.vmo_meta,
        timestamp: new Date().toISOString(),
        vertical,
      };
      setMessages((prev) => [...prev, agentMessage]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error occurred';
      setError(msg);
      console.error('[useCompassChat] Error:', msg);
    } finally {
      stopLoading();
    }
  }, []);

  const sendDualMessage = useCallback(async (query: string, vertical: string) => {
    if (!query.trim() || !vertical) {
      setError('Query and vertical are required');
      return;
    }

    const messageId = `msg-${++messageCountRef.current}`;
    startLoading();
    setError(null);

    const userMessage: ChatMessage = {
      id: `user-${messageId}`,
      type: 'user',
      result: query,
      timestamp: new Date().toISOString(),
      vertical,
    };

    // Add user message immediately
    setDualMessages((prev) => {
      const updated = [...prev, { id: messageId, userMessage }];
      saveDualMessages(updated);
      return updated;
    });

    let withDbData: any = null;
    let independentData: any = null;
    let completedCount = 0;

    const onBothDone = () => {
      completedCount++;
      if (completedCount === 2) {
        stopLoading();
        
        // Clean up pending cache once both responses are complete
        const cached = pendingResponses.get(messageId);
        if (cached?.withDb && cached?.independent) {
          pendingResponses.delete(messageId);
        }
        
        if (withDbData && independentData) {
          logDualResponses(query, vertical, withDbData, independentData);
        }
      }
    };

    // Helper to update state OR cache if component is unmounted
    const updateMessage = (side: 'withDb' | 'independent', msg: ChatMessage) => {
      // Always cache in module-level map first
      const cached = pendingResponses.get(messageId) || {};
      if (side === 'withDb') cached.withDb = msg;
      else cached.independent = msg;
      pendingResponses.set(messageId, cached);

      // Update state if component is mounted
      if (isMountedRef.current) {
        setDualMessages((prev) => {
          const updated = prev.map((m) =>
            m.id === messageId
              ? side === 'withDb'
                ? { ...m, withDbResponse: msg }
                : { ...m, independentResponse: msg }
              : m
          );
          saveDualMessages(updated);
          return updated;
        });
      } else {
        // If unmounted, just save to localStorage directly
        const stored = localStorage.getItem(COMPASS_DUAL_CHAT_STORAGE_KEY);
        if (stored) {
          try {
            const messages: DualColumnMessage[] = JSON.parse(stored);
            const updated = messages.map((m) =>
              m.id === messageId
                ? side === 'withDb'
                  ? { ...m, withDbResponse: msg }
                  : { ...m, independentResponse: msg }
                : m
            );
            saveDualMessages(updated);
          } catch (e) {
            console.error('Failed to update localStorage:', e);
          }
        }
      }
    };

    // WITH DB
    fetch('/api/chat/compass', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, vertical, temperature: 0.7, max_tokens: 2000 }),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        withDbData = data;
        const msg: ChatMessage = {
          id: `agent-with-db-${messageId}`,
          type: 'agent',
          thinking: data.thinking,
          result: data.result,
          vmo_meta: data.vmo_meta,
          timestamp: new Date().toISOString(),
          vertical,
        };
        updateMessage('withDb', msg);
      })
      .catch((err) => {
        const errMsg = err instanceof Error ? err.message : 'Unknown error';
        setError(errMsg);
        console.error('[useCompassChat] WithDb Error:', errMsg);
      })
      .finally(onBothDone);

    // INDEPENDENT
    fetch('/api/chat/compass/independent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, vertical, temperature: 0.7, max_tokens: 2000 }),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        independentData = data;
        const msg: ChatMessage = {
          id: `agent-independent-${messageId}`,
          type: 'agent',
          thinking: data.thinking,
          result: data.result,
          timestamp: new Date().toISOString(),
          vertical,
        };
        updateMessage('independent', msg);
      })
      .catch((err) => {
        const errMsg = err instanceof Error ? err.message : 'Unknown error';
        setError(errMsg);
        console.error('[useCompassChat] Independent Error:', errMsg);
      })
      .finally(onBothDone);
  }, []);

  const logDualResponses = async (
    query: string,
    vertical: string,
    withDbData: any,
    independentData: any
  ) => {
    try {
      await fetch('/api/chat/compass/log-dual', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          vertical,
          system_prompt_compass: withDbData.system_prompt_compass || '',
          thinking_compass: withDbData.thinking || '',
          response_compass: withDbData.result || '',
          system_prompt_independent: independentData.system_prompt_independent || '',
          thinking_independent: independentData.thinking || '',
          response_independent: independentData.result || '',
          context_data: withDbData.context_data || '',
        }),
      });
    } catch (err) {
      console.error('[useCompassChat] Failed to log dual responses:', err);
    }
  };

  const clearMessages = useCallback(() => {
    setMessages([]);
    setDualMessages([]);
    setError(null);
    messageCountRef.current = 0;
    pendingResponses.clear();
  }, []);

  const removeMessage = useCallback((id: string) => {
    setMessages((prev) => prev.filter((msg) => msg.id !== id));
    setDualMessages((prev) => prev.filter((msg) => msg.id !== id));
    pendingResponses.delete(id);
  }, []);

  return {
    messages,
    dualMessages,
    isLoading,
    error,
    sendMessage,
    sendDualMessage,
    clearMessages,
    removeMessage,
  };
};
