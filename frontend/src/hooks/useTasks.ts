import { useState, useEffect } from "react";
import { fetchTasks } from "../services/api";
import type { Task } from "../types";

export const useTasks = () => {
  const [tasks, setTasks] = useState<Task[]>([]);

  useEffect(() => {
    fetchTasks().then(setTasks);
  }, []);

  return { tasks };
};
