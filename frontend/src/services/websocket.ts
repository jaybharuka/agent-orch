export const createWebSocket = (url: string): WebSocket => {
  return new WebSocket(url);
};
