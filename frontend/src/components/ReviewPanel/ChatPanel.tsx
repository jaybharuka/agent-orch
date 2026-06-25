import React, { useEffect, useState } from "react";
import { useReviews } from "../../hooks/useReviews";
import type { ChatMessage } from "../../types";

interface ChatPanelProps {
  requestId: string;
}

const ChatPanel: React.FC<ChatPanelProps> = ({ requestId }: ChatPanelProps) => {
  const { messages, loadChat, sendChat } = useReviews();
  const [input, setInput] = useState("");

  useEffect(() => {
    loadChat(requestId);
    const interval = setInterval(() => {
      loadChat(requestId);
    }, 3000);
    return () => clearInterval(interval);
  }, [requestId, loadChat]);

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    sendChat(requestId, input.trim(), "human").then(() => setInput(""));
  };

  return (
    <div className="flex flex-col h-96 border rounded-lg bg-white">
      <div className="p-3 border-b font-semibold text-gray-700">
        Chat with Agent
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.map((msg: ChatMessage, idx: number) => (
          <div
            key={idx}
            className={`flex ${
              msg.role === "human" ? "justify-end" : "justify-start"
            }`}
          >
            <div
              className={`max-w-xs md:max-w-sm px-3 py-2 rounded-lg text-sm ${
                msg.role === "human"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 text-gray-800"
              }`}
            >
              <div className="text-xs font-semibold mb-1">
                {msg.role === "human" ? "You" : "Agent"}
              </div>
              <div>{msg.content}</div>
              <div className="text-xs opacity-70 mt-1">
                {new Date(msg.timestamp).toLocaleTimeString()}
              </div>
            </div>
          </div>
        ))}
        {messages.length === 0 && (
          <div className="text-center text-gray-400 text-sm mt-8">
            No messages yet.
          </div>
        )}
      </div>
      <form onSubmit={handleSend} className="p-3 border-t flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          className="flex-1 border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          type="submit"
          className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700"
        >
          Send
        </button>
      </form>
    </div>
  );
};

export default ChatPanel;
