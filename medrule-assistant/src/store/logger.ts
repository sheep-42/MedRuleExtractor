// src/store/logger.ts

import { defineStore } from 'pinia';
import { ref } from 'vue';

export interface LogEntry {
  id: number;
  type: string; // 'LOG', 'ERROR', 'SYSTEM', 'SUCCESS', 'FAILURE' 等
  message: string;
  timestamp: string;
}

export const useLoggerStore = defineStore('logger', () => {
  const logs = ref<LogEntry[]>([]);
  let logIdCounter = 0;

  function addLog(log: Omit<LogEntry, 'id' | 'timestamp'>) {
    const now = new Date();
    logs.value.push({
      ...log,
      id: logIdCounter++,
      timestamp: now.toLocaleTimeString(),
    });
  }

  function clearLogs() {
    logs.value = [];
    addLog({ type: 'SYSTEM', message: '日志已清空。' });
  }

  return {
    logs,
    addLog,
    clearLogs,
  };
});