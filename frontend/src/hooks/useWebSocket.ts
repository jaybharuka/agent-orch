import { useEffect, useRef } from "react";

export const useWebSocket = (url: string) => {
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    ws.current = new WebSocket(url);
    return () => {
      ws.current?.close();
    };
  }, [url]);

  return ws.current;
};
