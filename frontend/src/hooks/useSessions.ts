import { useState, useEffect } from "react";
import { fetchSessions } from "../services/api";
import type { Session } from "../types";

export const useSessions = () => {
  const [sessions, setSessions] = useState<Session[]>([]);

  useEffect(() => {
    fetchSessions().then(setSessions);
  }, []);

  return { sessions };
};
