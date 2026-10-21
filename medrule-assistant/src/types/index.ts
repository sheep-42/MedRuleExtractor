// src/types/index.ts
export interface FileNode {
  name: string;
  path: string;
  is_dir: boolean;
  children?: FileNode[]; // 用于树形结构
}