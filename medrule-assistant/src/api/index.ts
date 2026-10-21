// src/api/index.ts
import axios from 'axios';
import type { FileNode } from '../types';

const apiClient = axios.create({
  baseURL: '/api', // 后端 API 地址
  headers: {
    'Content-Type': 'application/json',
  },
});

export const browseDirectory = (path: string = '.'): Promise<FileNode[]> => {
  return apiClient.get('/browse', { params: { path } }).then(res => res.data);
};

export const previewFile = (path: string): Promise<any> => {
  return apiClient.post('/preview', { path }).then(res => res.data);
};

export const saveFile = (path: string, content: any): Promise<any> => {
  return apiClient.post('/save', { path, content }).then(res => res.data);
};

export interface DiffData {
  before: any;
  after: any;
}

export const logEdit = (filePath: string, diff: DiffData): Promise<any> => {
  const payload = {
    file_path: filePath,
    timestamp: new Date().toISOString(),
    diff: diff,
  };
  return apiClient.post('/log_edit', payload).then(res => res.data);
};