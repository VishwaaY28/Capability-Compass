import React, { useState, useEffect, useRef } from 'react';
import { FiSend, FiTrash2, FiChevronDown, FiLoader, FiDownload, FiChevronLeft, FiChevronRight } from 'react-icons/fi';
import ReactMarkdown from 'react-markdown';
import toast from 'react-hot-toast';
import pdfMake from 'pdfmake/build/pdfmake';
import { useCompassChat, type ChatMessage } from '../hooks/useCompassChat';
import { useCapabilityApi } from '../hooks/useCapability';

// Initialize pdfMake (vfs is loaded from vfs_fonts automatically in build)
let pdfMakeInitialized = false;

const initializePdfMake = async () => {
  if (pdfMakeInitialized) return;
  try {
    const vfsModule = await import('pdfmake/build/vfs_fonts');
    if (vfsModule && (vfsModule as any).pdfMake?.vfs) {
      (pdfMake as any).vfs = (vfsModule as any).pdfMake.vfs;
    }
    pdfMakeInitialized = true;
  } catch (e) {
    console.warn('Failed to load pdfmake fonts:', e);
  }
};

interface Vertical {
  id: number;
  name: string;
}


type CardLayout = 'both' | 'left-only' | 'right-only';

const CompassChat: React.FC = () => {
  const [query, setQuery] = useState('');
  const [selectedVertical, setSelectedVertical] = useState<string>('');
  const [verticals, setVerticals] = useState<Vertical[]>([]);
  const [showThinking, setShowThinking] = useState<{ [key: string]: boolean }>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [isLoadingVerticals, setIsLoadingVerticals] = useState(true);
  const [cardLayout, setCardLayout] = useState<CardLayout>('both');

  const { dualMessages, isLoading, error, sendDualMessage, clearMessages } = useCompassChat();
  const { listVerticals } = useCapabilityApi();

  // Load verticals on mount
  useEffect(() => {
    const loadVerticals = async () => {
      try {
        setIsLoadingVerticals(true);
        const data = await listVerticals();
        setVerticals(data);
        if (data.length > 0) {
          setSelectedVertical(data[0].name);
        }
      } catch (err) {
        console.error('Failed to load verticals:', err);
        toast.error('Failed to load verticals');
      } finally {
        setIsLoadingVerticals(false);
      }
    };

    loadVerticals();
  }, [listVerticals]);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [dualMessages]);

  // Handle errors
  useEffect(() => {
    if (error) {
      toast.error(error);
    }
  }, [error]);

  // DEBUG: Log independent responses to help identify missing results
  useEffect(() => {
    dualMessages.forEach((msg) => {
      if (msg.independentResponse) {
        const hasThinking = !!(msg.independentResponse.thinking && msg.independentResponse.thinking.trim());
        const hasResult = !!(msg.independentResponse.result && msg.independentResponse.result.trim());
        
        console.log('[Debug] Independent Response Details:', {
          timestamp: new Date().toISOString(),
          hasThinking,
          hasResult,
          thinkingLength: msg.independentResponse.thinking?.length || 0,
          resultLength: msg.independentResponse.result?.length || 0,
          thinkingPreview: msg.independentResponse.thinking?.substring(0, 100),
          resultPreview: msg.independentResponse.result?.substring(0, 100),
          fullResponse: msg.independentResponse,
        });
        
        // Warn if result is missing
        if (!hasResult) {
          console.warn('[Warning] Independent response has no result!', {
            query: msg.userQuery,
            thinking: msg.independentResponse.thinking?.substring(0, 200),
          });
        }
      }
    });
  }, [dualMessages]);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!query.trim()) {
      toast.error('Please enter a message');
      return;
    }

    if (!selectedVertical) {
      toast.error('Please select a vertical');
      return;
    }

    await sendDualMessage(query, selectedVertical);
    setQuery('');
  };

  const toggleThinking = (messageId: string, side: 'db' | 'independent') => {
    const key = `${messageId}-${side}`;
    setShowThinking((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const exportToPDF = async () => {
    try {
      await initializePdfMake();

      // Helper function to clean text
      const cleanText = (text: string): string => {
        if (!text) return '';
        const textArea = document.createElement('textarea');
        textArea.innerHTML = text;
        return textArea.value
          .replace(/&nbsp;/g, ' ')
          .replace(/&amp;/g, '&')
          .replace(/&lt;/g, '<')
          .replace(/&gt;/g, '>')
          .replace(/&quot;/g, '"')
          .replace(/&#039;/g, "'")
          .replace(/[\u200B-\u200D\uFEFF]/g, '')
          .replace(/\s+/g, ' ')
          .trim();
      };

      // Helper function to parse bold text in pdfMake format
      const parseBoldText = (text: string): any => {
        const parts: any[] = [];
        const regex = /\*\*(.*?)\*\*|([^\*]+)/g;
        let match;

        while ((match = regex.exec(text)) !== null) {
          if (match[1]) {
            // Bold text
            parts.push({
              text: cleanText(match[1]),
              bold: true,
            });
          } else if (match[2]) {
            // Regular text
            parts.push(cleanText(match[2]));
          }
        }

        return parts.length > 0 ? parts : cleanText(text);
      };

      // Helper function to parse thinking text into formatted content
      const parseThinkingText = (text: string): any[] => {
        const content: any[] = [];
        const paragraphs = text.split('\n\n');

        paragraphs.forEach((para) => {
          const lines = para.trim().split('\n');
          let currentList: any[] = [];
          let isNumberedList = false;

          lines.forEach((line) => {
            const trimmedLine = line.trim();

            if (!trimmedLine) {
              // End current list if exists
              if (currentList.length > 0) {
                if (isNumberedList) {
                  content.push({
                    ol: currentList,
                    margin: [0, 2, 0, 2],
                  });
                } else {
                  content.push({
                    ul: currentList,
                    margin: [0, 2, 0, 2],
                  });
                }
                currentList = [];
              }
              return;
            }

            // Handle bullet points
            if (trimmedLine.match(/^[-•*]\s+/)) {
              if (isNumberedList && currentList.length > 0) {
                // Switch from numbered to bullet list
                content.push({
                  ol: currentList,
                  margin: [0, 2, 0, 2],
                });
                currentList = [];
              }
              isNumberedList = false;
              const bulletText = trimmedLine.replace(/^[-•*]\s+/, '');
              currentList.push({
                text: parseBoldText(bulletText),
                fontSize: 11,
                color: '#505050',
              });
            }
            // Handle numbered lists
            else if (trimmedLine.match(/^\d+[.)]\s+/)) {
              if (!isNumberedList && currentList.length > 0) {
                // Switch from bullet to numbered list
                content.push({
                  ul: currentList,
                  margin: [0, 2, 0, 2],
                });
                currentList = [];
              }
              isNumberedList = true;
              const match = trimmedLine.match(/^\d+[.)]\s+(.*)/);
              if (match) {
                currentList.push({
                  text: parseBoldText(match[1]),
                  fontSize: 11,
                  color: '#505050',
                });
              }
            }
            // Handle headers (lines ending with colon or all caps)
            else if (trimmedLine.endsWith(':') || (trimmedLine.length > 3 && trimmedLine === trimmedLine.toUpperCase())) {
              // End current list if exists
              if (currentList.length > 0) {
                if (isNumberedList) {
                  content.push({
                    ol: currentList,
                    margin: [0, 2, 0, 2],
                  });
                } else {
                  content.push({
                    ul: currentList,
                    margin: [0, 2, 0, 2],
                  });
                }
                currentList = [];
              }
              content.push({
                text: parseBoldText(trimmedLine),
                fontSize: 12,
                bold: true,
                color: '#333333',
                margin: [0, 8, 0, 4],
              });
            }
            // Regular text
            else {
              // End current list if exists
              if (currentList.length > 0) {
                if (isNumberedList) {
                  content.push({
                    ol: currentList,
                    margin: [0, 2, 0, 2],
                  });
                } else {
                  content.push({
                    ul: currentList,
                    margin: [0, 2, 0, 2],
                  });
                }
                currentList = [];
              }
              content.push({
                text: parseBoldText(trimmedLine),
                fontSize: 11,
                color: '#505050',
                alignment: 'justify',
                margin: [0, 2, 0, 2],
              });
            }
          });

          // End list at end of paragraph
          if (currentList.length > 0) {
            if (isNumberedList) {
              content.push({
                ol: currentList,
                margin: [0, 2, 0, 2],
              });
            } else {
              content.push({
                ul: currentList,
                margin: [0, 2, 0, 2],
              });
            }
          }
        });

        return content;
      };

      // Helper function to parse response text into formatted content (supports markdown-like formatting)
      const parseResponseText = (text: string): any[] => {
        const content: any[] = [];
        const paragraphs = text.split('\n\n');

        paragraphs.forEach((para) => {
          const lines = para.trim().split('\n');
          let currentList: any[] = [];
          let isNumberedList = false;

          lines.forEach((line) => {
            const trimmedLine = line.trim();

            if (!trimmedLine) {
              // End current list if exists
              if (currentList.length > 0) {
                if (isNumberedList) {
                  content.push({
                    ol: currentList,
                    margin: [0, 2, 0, 2],
                  });
                } else {
                  content.push({
                    ul: currentList,
                    margin: [0, 2, 0, 2],
                  });
                }
                currentList = [];
              }
              return;
            }

            // Handle markdown headers (## h2, ### h3, etc.)
            if (trimmedLine.match(/^#{1,6}\s+/)) {
              // End current list if exists
              if (currentList.length > 0) {
                if (isNumberedList) {
                  content.push({
                    ol: currentList,
                    margin: [0, 2, 0, 2],
                  });
                } else {
                  content.push({
                    ul: currentList,
                    margin: [0, 2, 0, 2],
                  });
                }
                currentList = [];
              }

              const match = trimmedLine.match(/^(#{1,6})\s+(.*)/);
              if (match) {
                const headerLevel = match[1].length;
                const headerText = match[2];
                const fontSizes = { 1: 16, 2: 14, 3: 13, 4: 12, 5: 11, 6: 10 };
                content.push({
                  text: parseBoldText(headerText),
                  fontSize: fontSizes[headerLevel] || 12,
                  bold: true,
                  color: '#1a1a1a',
                  margin: [0, 8, 0, 4],
                });
              }
            }
            // Handle bullet points
            else if (trimmedLine.match(/^[-•*]\s+/)) {
              if (isNumberedList && currentList.length > 0) {
                // Switch from numbered to bullet list
                content.push({
                  ol: currentList,
                  margin: [0, 2, 0, 2],
                });
                currentList = [];
              }
              isNumberedList = false;
              const bulletText = trimmedLine.replace(/^[-•*]\s+/, '');
              currentList.push({
                text: parseBoldText(bulletText),
                fontSize: 11,
                color: '#505050',
              });
            }
            // Handle numbered lists
            else if (trimmedLine.match(/^\d+[.)]\s+/)) {
              if (!isNumberedList && currentList.length > 0) {
                // Switch from bullet to numbered list
                content.push({
                  ul: currentList,
                  margin: [0, 2, 0, 2],
                });
                currentList = [];
              }
              isNumberedList = true;
              const match = trimmedLine.match(/^\d+[.)]\s+(.*)/);
              if (match) {
                currentList.push({
                  text: parseBoldText(match[1]),
                  fontSize: 11,
                  color: '#505050',
                });
              }
            }
            // Handle bold text (**text**)
            else if (trimmedLine.includes('**')) {
              // End current list if exists
              if (currentList.length > 0) {
                if (isNumberedList) {
                  content.push({
                    ol: currentList,
                    margin: [0, 2, 0, 2],
                  });
                } else {
                  content.push({
                    ul: currentList,
                    margin: [0, 2, 0, 2],
                  });
                }
                currentList = [];
              }

              content.push({
                text: parseBoldText(trimmedLine),
                fontSize: 11,
                color: '#505050',
                alignment: 'justify',
                margin: [0, 2, 0, 2],
              });
            }
            // Handle inline code (`code`)
            else if (trimmedLine.includes('`')) {
              // End current list if exists
              if (currentList.length > 0) {
                if (isNumberedList) {
                  content.push({
                    ol: currentList,
                    margin: [0, 2, 0, 2],
                  });
                } else {
                  content.push({
                    ul: currentList,
                    margin: [0, 2, 0, 2],
                  });
                }
                currentList = [];
              }

              const parts: any[] = [];
              const regex = /`(.*?)`|([^`]+)/g;
              let match;
              while ((match = regex.exec(trimmedLine)) !== null) {
                if (match[1]) {
                  parts.push({
                    text: cleanText(match[1]),
                    background: '#f0f0f0',
                    color: '#1a1a1a',
                    font: 'Courier',
                    fontSize: 10,
                  });
                } else if (match[2]) {
                  parts.push(cleanText(match[2]));
                }
              }
              content.push({
                text: parts,
                fontSize: 11,
                color: '#505050',
                alignment: 'justify',
                margin: [0, 2, 0, 2],
              });
            }
            // Regular text
            else {
              // End current list if exists
              if (currentList.length > 0) {
                if (isNumberedList) {
                  content.push({
                    ol: currentList,
                    margin: [0, 2, 0, 2],
                  });
                } else {
                  content.push({
                    ul: currentList,
                    margin: [0, 2, 0, 2],
                  });
                }
                currentList = [];
              }

              content.push({
                text: parseBoldText(trimmedLine),
                fontSize: 11,
                color: '#505050',
                alignment: 'justify',
                margin: [0, 2, 0, 2],
              });
            }
          });

          // End list at end of paragraph
          if (currentList.length > 0) {
            if (isNumberedList) {
              content.push({
                ol: currentList,
                margin: [0, 2, 0, 2],
              });
            } else {
              content.push({
                ul: currentList,
                margin: [0, 2, 0, 2],
              });
            }
          }
        });

        return content;
      };

      // Build document definition for pdfmake
      const docDefinition: any = {
        pageSize: 'A4',
        pageMargins: [40, 40, 40, 40],
        defaultStyle: {
          font: 'Roboto',
          lineHeight: 1.5,
        },
        content: [
          {
            text: 'Compass Chat Export',
            fontSize: 18,
            bold: true,
            color: '#000000',
            margin: [0, 0, 0, 10],
          },
          {
            text: `Generated on: ${new Date().toLocaleString()}`,
            fontSize: 10,
            color: '#666666',
            margin: [0, 0, 0, 15],
          },
          {
            canvas: [
              {
                type: 'line',
                x1: 0,
                y1: 5,
                x2: 515 - 80,
                y2: 5,
                lineWidth: 1,
                lineColor: '#cccccc',
              },
            ],
            margin: [0, 0, 0, 15],
          },
        ],
        styles: {
          userLabel: {
            bold: true,
            fontSize: 14,
            color: '#000000',
            margin: [0, 10, 0, 5],
          },
          userText: {
            fontSize: 12,
            color: '#333333',
            margin: [10, 0, 0, 3],
            alignment: 'justify',
            lineHeight: 1.5,
          },
          verticalLabel: {
            fontSize: 12,
            color: '#666666',
            margin: [10, 0, 0, 8],
          },
          dbLabel: {
            bold: true,
            fontSize: 14,
            color: '#0066cc',
            margin: [0, 10, 0, 5],
          },
          dbThinkingLabel: {
            bold: true,
            fontSize: 13,
            color: '#3b82f6',
            margin: [0, 5, 0, 5],
          },
          dbAnalysisLabel: {
            bold: true,
            fontSize: 13,
            color: '#059669',
            margin: [0, 8, 0, 5],
          },
          independentLabel: {
            bold: true,
            fontSize: 12,
            color: '#8b5cf6',
            margin: [0, 10, 0, 5],
          },
          timestamp: {
            fontSize: 9,
            color: '#999999',
            alignment: 'right',
            margin: [0, 5, 0, 0],
          },
        },
      };

      // Add messages to the document
      dualMessages.forEach((dualMsg, msgIndex) => {
        // User Message
        const content = docDefinition.content;

        content.push(
          { text: 'You:', style: 'userLabel' },
          { text: cleanText(dualMsg.userMessage.result), style: 'userText' }
        );

        if (dualMsg.userMessage.vertical) {
          content.push({
            text: `Vertical: ${cleanText(dualMsg.userMessage.vertical)}`,
            style: 'verticalLabel',
          });
        }

        // VMO Metadata Section (if available)
        if (dualMsg.withDbResponse?.vmo_meta) {
          const metaData = dualMsg.withDbResponse.vmo_meta;
          if (metaData) {
            content.push({
              text: 'Intent Analysis',
              fontSize: 11,
              bold: true,
              color: '#0066cc',
              margin: [0, 8, 0, 4],
            });

            const metaTable = {
              table: {
                headerRows: 0,
                widths: ['30%', '70%'],
                body: [
                  [
                    {
                      text: 'Persona',
                      fontSize: 10,
                      bold: true,
                      color: '#ffffff',
                      fillColor: '#0066cc',
                      padding: [6, 4],
                    },
                    {
                      text: metaData.persona || '-',
                      fontSize: 10,
                      color: '#333333',
                      padding: [6, 4],
                      fillColor: '#f5f5f5',
                    },
                  ],
                  [
                    {
                      text: 'Intent',
                      fontSize: 10,
                      bold: true,
                      color: '#ffffff',
                      fillColor: '#0066cc',
                      padding: [6, 4],
                    },
                    {
                      text: metaData.intent || '-',
                      fontSize: 10,
                      color: '#333333',
                      padding: [6, 4],
                    },
                  ],
                  [
                    {
                      text: 'Primary Anchors',
                      fontSize: 10,
                      bold: true,
                      color: '#ffffff',
                      fillColor: '#0066cc',
                      padding: [6, 4],
                    },
                    {
                      text: Array.isArray(metaData.primary_anchors)
                        ? metaData.primary_anchors.join(', ')
                        : (metaData.primary_anchors || '-'),
                      fontSize: 10,
                      color: '#333333',
                      padding: [6, 4],
                      fillColor: '#f5f5f5',
                    },
                  ],
                ],
              },
              layout: {
                hLineWidth: () => 1,
                vLineWidth: () => 1,
                hLineColor: '#cccccc',
                vLineColor: '#cccccc',
              },
              margin: [0, 0, 0, 8],
            };
            content.push(metaTable);
          }
        }

        // DB Response
        if (dualMsg.withDbResponse) {
          content.push({ text: 'Using Capability Compass', style: 'dbLabel' });

          if (dualMsg.withDbResponse.thinking) {
            content.push({
              text: 'LLM Thinking Process:',
              style: 'dbThinkingLabel',
            });

            // Parse and add formatted thinking content
            const thinkingContent = parseThinkingText(dualMsg.withDbResponse.thinking);
            content.push({
              stack: thinkingContent,
              margin: [15, 0, 0, 10],
            });
          }

          if (dualMsg.withDbResponse.result) {
            content.push({
              text: 'LLM Response:',
              style: 'dbAnalysisLabel',
            });

            // Parse and add formatted response content
            const responseContent = parseResponseText(dualMsg.withDbResponse.result);
            content.push({
              stack: responseContent,
              margin: [15, 0, 0, 10],
            });
          }
        }

        // Independent Response
        if (dualMsg.independentResponse) {
          content.push({
            text: 'Without Capability Compass',
            style: 'independentLabel',
          });

          if (dualMsg.independentResponse.thinking) {
            content.push({
              text: 'LLM Thinking Process:',
              style: 'dbThinkingLabel',
            });

            // Parse and add formatted thinking content
            const thinkingContent = parseThinkingText(dualMsg.independentResponse.thinking);
            content.push({
              stack: thinkingContent,
              margin: [15, 0, 0, 10],
            });
          }

          if (dualMsg.independentResponse.result) {
            content.push({
              text: 'LLM Response:',
              style: 'dbAnalysisLabel',
            });

            // Parse and add formatted response content
            const responseContent = parseResponseText(dualMsg.independentResponse.result);
            content.push({
              stack: responseContent,
              margin: [15, 0, 0, 10],
            });
          }
        }

        // Message separator
        if (msgIndex < dualMessages.length - 1) {
          content.push({
            canvas: [
              {
                type: 'line',
                x1: 0,
                y1: 5,
                x2: 515 - 80,
                y2: 5,
                lineWidth: 1,
                lineColor: '#eeeeee',
              },
            ],
            margin: [0, 15, 0, 15],
          });
        }

        // Timestamp
        content.push({
          text: new Date(dualMsg.userMessage.timestamp || Date.now()).toLocaleTimeString(),
          style: 'timestamp',
        });
      });

      // Generate and download PDF
      pdfMake.createPdf(docDefinition).download(
        `compass-chat-${new Date().toLocaleString().replace(/[/:]/g, '-')}.pdf`
      );
      toast.success('Chat exported to PDF successfully!');
    } catch (err) {
      console.error('Failed to export PDF:', err);
      toast.error('Failed to export chat to PDF');
    }
  };

  const renderMessage = (message: ChatMessage | undefined, messageId: string, side: 'db' | 'independent') => {
    if (!message) {
      return (
        <div className="space-y-3">
          <div className="bg-gradient-to-r from-blue-50 to-blue-25 border border-blue-200 rounded-lg p-4 text-center">
            <div className="flex items-center justify-center gap-2">
              <FiLoader className="animate-spin text-blue-600" size={16} />
              <p className="text-sm text-gray-600 font-medium">
                {side === 'db' ? 'LLM answering using Capability Compass context...' : 'LLM answering without using Capability Compass context...'}
              </p>
            </div>
          </div>
        </div>
      );
    }

    const thinkingKey = `${messageId}-${side}`;
    const isThinkingVisible = showThinking[thinkingKey] || false;
  // Use message-scoped VMO metadata (attached when response arrives)
  const metaToShow = side === 'db' ? message.vmo_meta : null;

    return (
      <div className="space-y-2">
        {/* Thinking Section - Collapsible Dropdown */}
        {message.thinking && (
          <div className="border border-blue-200 rounded-lg bg-gradient-to-r from-blue-50 to-blue-25 overflow-hidden">
            <button
              onClick={() => toggleThinking(messageId, side)}
              className="w-full px-5 py-4 flex items-center justify-between hover:bg-blue-100 transition-colors group"
            >
              <div className="flex items-center gap-3">
                <span className={`text-blue-600 transition-transform ${isThinkingVisible ? 'rotate-90' : ''}`}>
                  ➡️
                </span>
                <span className="text-base font-semibold text-gray-800 group-hover:text-blue-900">
                  LLM Thinking Process
                </span>
              </div>
              <span className="text-xs font-medium text-blue-600 px-2 py-1 bg-blue-100 rounded">
                {isThinkingVisible ? 'Hide' : 'Show'}
              </span>
            </button>

            {isThinkingVisible && (
              <div className="border-t border-blue-200 px-5 py-5 bg-white">
                <div className="space-y-4">
                  {message.thinking.split('\n\n').map((paragraph, idx) => {
                    // Parse bullet points and numbered lists
                    const lines = paragraph.trim().split('\n');

                    // Helper function to render text with bold formatting
                    const renderTextWithBold = (text: string) => {
                      const parts: any[] = [];
                      const regex = /\*\*(.*?)\*\*|([^\*]+)/g;
                      let match;
                      let lastIndex = 0;

                      while ((match = regex.exec(text)) !== null) {
                        if (match[1]) {
                          // Bold text
                          parts.push(
                            <strong key={`${idx}-${lastIndex}-bold`} className="font-bold text-gray-900">
                              {match[1]}
                            </strong>
                          );
                        } else if (match[2]) {
                          // Regular text
                          parts.push(
                            <span key={`${idx}-${lastIndex}-text`} className="text-gray-700">
                              {match[2]}
                            </span>
                          );
                        }
                        lastIndex++;
                      }

                      return parts.length > 0 ? parts : text;
                    };

                    return (
                      <div key={idx} className="text-gray-700 leading-relaxed">
                        {lines.map((line, lineIdx) => {
                          const trimmedLine = line.trim();
                          // Handle bullet points
                          if (trimmedLine.match(/^[-•*]\s+/)) {
                            const bulletText = trimmedLine.replace(/^[-•*]\s+/, '');
                            return (
                              <div key={lineIdx} className="flex gap-3 mb-2 text-base font-normal">
                                <span className="text-blue-500 flex-shrink-0 mt-0.5">•</span>
                                <span className="text-gray-700">{renderTextWithBold(bulletText)}</span>
                              </div>
                            );
                          }
                          // Handle numbered lists
                          if (trimmedLine.match(/^\d+[.)]\s+/)) {
                            const number = trimmedLine.match(/^\d+/)[0];
                            const itemText = trimmedLine.replace(/^\d+[.)]\s+/, '');
                            return (
                              <div key={lineIdx} className="flex gap-3 mb-2 text-base font-normal">
                                <span className="text-blue-600 flex-shrink-0 font-semibold">{number}.</span>
                                <span className="text-gray-700">{renderTextWithBold(itemText)}</span>
                              </div>
                            );
                          }
                          // Handle headers (lines ending with colon or in caps)
                          if (trimmedLine.endsWith(':') || (trimmedLine.length > 0 && trimmedLine === trimmedLine.toUpperCase() && trimmedLine.length > 3)) {
                            return (
                              <div key={lineIdx} className="font-semibold text-gray-900 text-base mb-2 mt-2">
                                {renderTextWithBold(trimmedLine)}
                              </div>
                            );
                          }
                          // Regular text
                          if (trimmedLine.length > 0) {
                            return (
                              <p key={lineIdx} className="text-gray-700 text-base leading-7 mb-2 font-normal">
                                {renderTextWithBold(trimmedLine)}
                              </p>
                            );
                          }
                          return null;
                        })}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Result Section */}
        <div className="bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
          <h4 className="text-base font-semibold text-gray-900 mb-4 pb-3 border-b border-gray-100">
            LLM Response
          </h4>
          <div className="text-gray-800 leading-relaxed">
            {/* Inline VMO metadata for the thinking LLM (db side) - shown before the result */}
            {metaToShow && (
              <div className="mb-5 p-4 bg-gradient-to-r from-gray-50 to-gray-25 rounded-lg border border-gray-200">
                <div className="text-sm text-gray-700 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-gray-900">Persona:</span>
                    <span className="text-gray-700">{metaToShow.persona || '-'}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-gray-900">Intent:</span>
                    <span className="text-gray-700">{metaToShow.intent || '-'}</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="font-semibold text-gray-900 flex-shrink-0">Anchors:</span>
                    <span className="text-gray-700">
                      {Array.isArray(metaToShow.primary_anchors) ? metaToShow.primary_anchors.join(', ') : (metaToShow.primary_anchors || '-')}
                    </span>
                  </div>
                </div>
              </div>
            )}

            <div className="prose prose-sm prose-gray max-w-none font-inter">
              <ReactMarkdown
                components={{
                  p: ({ children }) => (
                    <p className="text-gray-800 mb-4 leading-7 text-base font-normal">
                      {children}
                    </p>
                  ),
                  h1: ({ children }) => (
                    <h1 className="text-3xl font-bold mb-5 mt-6 text-gray-900 font-inter">
                      {children}
                    </h1>
                  ),
                  h2: ({ children }) => (
                    <h2 className="text-2xl font-bold mb-4 mt-5 text-gray-900 font-inter">
                      {children}
                    </h2>
                  ),
                  h3: ({ children }) => (
                    <h3 className="text-xl font-semibold mb-3 mt-4 text-gray-800 font-inter">
                      {children}
                    </h3>
                  ),
                  h4: ({ children }) => (
                    <h4 className="text-lg font-semibold mb-3 mt-3 text-gray-800 font-inter">
                      {children}
                    </h4>
                  ),
                  ul: ({ children }) => (
                    <ul className="list-disc list-outside mb-4 ml-5 space-y-2 text-gray-800">
                      {children}
                    </ul>
                  ),
                  ol: ({ children }) => (
                    <ol className="list-decimal list-outside mb-4 ml-5 space-y-2 text-gray-800">
                      {children}
                    </ol>
                  ),
                  li: ({ children }) => (
                    <li className="text-gray-800 text-base leading-7 mb-2">
                      {children}
                    </li>
                  ),
                  code: ({ inline, children }: any) =>
                    inline ? (
                      <code className="inline-block bg-gray-100 text-gray-900 px-2 py-1 rounded font-mono text-sm border border-gray-200">
                        {children}
                      </code>
                    ) : (
                      <pre className="block bg-gray-900 text-gray-100 p-4 rounded-lg mb-4 overflow-x-auto font-mono text-sm border border-gray-700">
                        <code>
                          {children}
                        </code>
                      </pre>
                    ),
                  blockquote: ({ children }) => (
                    <blockquote className="border-l-4 border-blue-500 pl-4 italic text-gray-700 my-4 bg-blue-50 py-3 pr-4 rounded-r">
                      {children}
                    </blockquote>
                  ),
                  a: ({ href, children }) => (
                    <a
                      href={href}
                      className="text-blue-600 hover:text-blue-700 underline transition-colors font-medium"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {children}
                    </a>
                  ),
                  table: ({ children }) => (
                    <div className="overflow-x-auto mb-4">
                      <table className="w-full border-collapse border border-gray-300 rounded-lg overflow-hidden">
                        {children}
                      </table>
                    </div>
                  ),
                  tr: ({ children }) => (
                    <tr className="border border-gray-300 hover:bg-gray-50 transition-colors">
                      {children}
                    </tr>
                  ),
                  td: ({ children }) => (
                    <td className="border border-gray-300 px-4 py-3 text-gray-800 text-base">
                      {children}
                    </td>
                  ),
                  th: ({ children }) => (
                    <th className="border border-gray-300 px-4 py-3 bg-gray-200 font-semibold text-left text-gray-900">
                      {children}
                    </th>
                  ),
                  hr: () => (
                    <hr className="my-5 border-t border-gray-300" />
                  ),
                  strong: ({ children }) => (
                    <strong className="font-bold text-gray-900">
                      {children}
                    </strong>
                  ),
                  em: ({ children }) => (
                    <em className="italic text-gray-700">
                      {children}
                    </em>
                  ),
                }}
              >
                {message.result}
              </ReactMarkdown>
            </div>
          </div>
        </div>

        {/* Timestamp */}
        <p className="text-xs font-medium text-gray-500 text-right px-2 mt-3">
          {new Date(message.timestamp).toLocaleTimeString()}
        </p>
      </div>
    );
  };

  return (
    <div className="flex flex-col h-screen bg-gradient-to-b from-gray-50 to-gray-100">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 shadow-sm p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
           {/* <img src={favicon} width={40} height={40} alt="favicon" /> */}
          <div>
              <h1 className="text-xl font-semibold">Compass Chat</h1>
               <p className="text-xs text-muted-foreground">
                  Resolve Your Organizational Queries
               </p>
          </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={exportToPDF}
              disabled={dualMessages.length === 0}
              className="flex items-center gap-2 px-4 py-2 text-green-600 hover:bg-green-50 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="Export chat to PDF"
            >
              <FiDownload size={18} />
              <span className="text-sm">Export PDF</span>
            </button>
            <button
              onClick={clearMessages}
              disabled={dualMessages.length === 0}
              className="flex items-center gap-2 px-4 py-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="Clear chat history"
            >
              <FiTrash2 size={18} />
              <span className="text-sm">Clear</span>
            </button>
          </div>
        </div>
      </div>

      {/* Messages Container - Two Columns */}
      <div className="flex-1 overflow-y-auto p-4">
        {dualMessages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <h2 className="text-2xl font-semibold text-gray-900 mb-2">Start a Conversation</h2>
              <p className="text-gray-500 max-w-md">
                Select a vertical and ask questions.
              </p>
            </div>
          </div>
        ) : (
          <>
            {dualMessages.map((dualMsg) => (
              <div key={dualMsg.id} className="mb-6">
                {/* User Message */}
                <div className="flex justify-end mb-4">
                  <div className="max-w-2xl rounded-lg p-4 bg-blue-600 text-white rounded-br-none shadow-sm">
                    <div>
                      {dualMsg.userMessage.vertical && (
                        <p className="text-xs opacity-75 mb-2">
                          Vertical: <span className="font-semibold">{dualMsg.userMessage.vertical}</span>
                        </p>
                      )}
                      <p className="text-sm break-words">{dualMsg.userMessage.result}</p>
                    </div>
                  </div>
                </div>

                {/* Two Column Responses */}
                <div className="max-w-6xl">
                  <div 
                    className={`grid gap-4 transition-all duration-300 ease-in-out ${
                      cardLayout === 'both' 
                        ? 'grid-cols-2' 
                        : 'grid-cols-1'
                    }`}
                  >
                    {/* Left Column - With Database Context */}
                    {(cardLayout === 'both' || cardLayout === 'left-only') && (
                      <div className="flex flex-col">
                        <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
                          {/* Card Header with Toggle */}
                          <div className="flex items-center justify-between mb-4 pb-4 border-b border-gray-200">
                            <div className="flex items-center gap-2">
                              <img src="/favicon.png" alt="Compass" className="w-10 h-10" />
                              <h3 className="text-sm font-semibold text-gray-900">
                                Using Capability Compass
                              </h3>
                            </div>
                            {cardLayout !== 'left-only' && (
                              <button
                                onClick={() => setCardLayout('left-only')}
                                className="p-1.5 hover:bg-gray-100 rounded-lg transition-colors duration-200"
                                title="Expand this card"
                              >
                                <FiChevronRight size={18} className="text-gray-500 hover:text-gray-700" />
                              </button>
                            )}
                            {cardLayout === 'left-only' && (
                              <button
                                onClick={() => setCardLayout('both')}
                                className="p-1.5 hover:bg-gray-100 rounded-lg transition-colors duration-200"
                                title="Expand this card"
                              >
                                <FiChevronLeft size={18} className="text-gray-500 hover:text-gray-700" />
                              </button>
                            )}
                          </div>

                          {renderMessage(
                            dualMsg.withDbResponse,
                            dualMsg.id,
                            'db'
                          )}
                        </div>
                      </div>
                    )}

                    {/* Right Column - Independent Thinking */}
                    {(cardLayout === 'both' || cardLayout === 'right-only') && (
                      <div className="flex flex-col">
                        <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
                          {/* Card Header with Toggle */}
                          <div className="flex items-center justify-between mb-4 pb-4 border-b border-gray-200">
                           <div className="flex items-center gap-2">
                              <img src="/llm.png" alt="llm" className="w-10 h-10" />
                              <h3 className="text-sm font-semibold text-gray-900">
                                Without Capability Compass
                              </h3>
                            </div>
                            {cardLayout !== 'right-only' && (
                              <button
                                onClick={() => setCardLayout('right-only')}
                                className="p-1.5 hover:bg-gray-100 rounded-lg transition-colors duration-200"
                                title="Expand this card"
                              >
                                <FiChevronLeft size={18} className="text-gray-500 hover:text-gray-700" />
                              </button>
                            )}
                            {cardLayout === 'right-only' && (
                              <button
                                onClick={() => setCardLayout('both')}
                                className="p-1.5 hover:bg-gray-100 rounded-lg transition-colors duration-200"
                                title="Expand this card"
                              >
                                <FiChevronRight size={18} className="text-gray-500 hover:text-gray-700" />
                              </button>
                            )}
                          </div>
                          {renderMessage(
                            dualMsg.independentResponse,
                            dualMsg.id,
                            'independent'
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}

            {/* Loading Indicator - Show only if there are no messages (first request) */}
            {isLoading && dualMessages.length === 0 && (
              <div className="grid grid-cols-2 gap-4 max-w-6xl mt-6">
                <div className="bg-gradient-to-r from-blue-50 to-blue-25 border border-blue-200 rounded-lg shadow-sm p-4">
                  <div className="flex items-center gap-2">
                    <FiLoader className="animate-spin text-blue-600" size={18} />
                    <p className="text-sm text-gray-700 font-medium">LLM answering using Capability Compass context...</p>
                  </div>
                </div>
                <div className="bg-gradient-to-r from-purple-50 to-purple-25 border border-purple-200 rounded-lg shadow-sm p-4">
                  <div className="flex items-center gap-2">
                    <FiLoader className="animate-spin text-purple-600" size={18} />
                    <p className="text-sm text-gray-700 font-medium">LLM answering without using Capability Compass context...</p>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input Area */}
      <div className="border-t border-gray-200 p-4 md:p-5">
        <form onSubmit={handleSendMessage}>
          <div className="max-w-4xl mx-auto">
            {/* Main Input Container */}
            <div className="relative bg-white rounded-2xl border border-gray-200 shadow-md hover:shadow-lg hover:border-gray-300 transition-all duration-200 focus-within:shadow-xl focus-within:border-blue-400 focus-within:ring-1 focus-within:ring-blue-200 flex items-center">
              {/* Vertical Selector - Left Side */}
              <div className="flex items-center h-full px-4 border-r border-gray-200">
                <div className="relative">
                  <select
                    value={selectedVertical}
                    onChange={(e) => setSelectedVertical(e.target.value)}
                    disabled={isLoadingVerticals || verticals.length === 0}
                    className="appearance-none bg-transparent text-gray-900 font-medium cursor-pointer pr-6 focus:outline-none text-sm md:text-base min-w-max hover:text-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <option value="">Select Vertical</option>
                    {verticals.map((v) => (
                      <option key={v.id} value={v.name}>
                        {v.name}
                      </option>
                    ))}
                  </select>
                  <FiChevronDown className="absolute right-0 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none text-sm" />
                </div>
              </div>

              {/* Input Field - Left Start */}
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={selectedVertical ? "Ask about capabilities, processes, or business operations..." : "Select a vertical to start..."}
                disabled={isLoading || !selectedVertical}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey && !isLoading && selectedVertical && query.trim()) {
                    handleSendMessage(e as any);
                  }
                }}
                className="w-full px-4 py-4 pl-4 pr-16 bg-transparent text-gray-900 placeholder-gray-400 focus:outline-none text-sm md:text-base disabled:placeholder-gray-300 disabled:cursor-not-allowed"
              />

              {/* Send Button - Right Side */}
              <button
                type="submit"
                disabled={isLoading || !selectedVertical || !query.trim()}
                className="px-4 py-2 text-gray-400 hover:text-blue-600 disabled:text-gray-300 disabled:hover:text-gray-300 transition-colors duration-200 disabled:cursor-not-allowed hover:bg-blue-50 rounded-lg mr-2"
                title={isLoading ? "Analyzing..." : "Send message (Enter)"}
              >
                {isLoading ? (
                  <FiLoader className="animate-spin" size={20} />
                ) : (
                  <FiSend size={20} className={`${!selectedVertical || !query.trim() ? 'opacity-50' : 'opacity-100'}`} />
                )}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};

export default CompassChat;
