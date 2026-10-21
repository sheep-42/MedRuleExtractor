// src/services/websocket.ts

import { useLoggerStore } from '../store/logger';

class WebSocketService {
  private socket: WebSocket | null = null;
  // private url: string;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;

  constructor() { // <-- 构造函数不再需要 url 参数
    // this.url = url;
  }

  public connect(): void {
    // 防止重复连接
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      console.log('WebSocket is already connected.');
      return;
    }

    // 生产环境下更优的动态 URL 生成方式
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host; // .host 包含了主机名和端口号
    const url = `${protocol}//${host}/ws/run-script`;
    // 在访问 http://my-domain.com 时，URL 会是 ws://my-domain.com/ws/run-script
    // Nginx 会自动把这个请求转发到后端的 5000 端口

    const loggerStore = useLoggerStore();
    loggerStore.addLog({ type: 'SYSTEM', message: '正在连接 WebSocket...' });

    this.socket = new WebSocket(url);

    this.socket.onopen = () => {
      console.log('WebSocket connected');
      loggerStore.addLog({ type: 'SYSTEM', message: 'WebSocket 连接成功！' });
      this.reconnectAttempts = 0; // 连接成功后重置重连次数
    };

    this.socket.onmessage = (event) => {
      // 后端发送的消息格式是 "PREFIX: message"
      const rawMessage = event.data;
      const separatorIndex = rawMessage.indexOf(':');
      
      let type = 'LOG';
      let message = rawMessage;

      if (separatorIndex > -1) {
        type = rawMessage.substring(0, separatorIndex).trim();
        message = rawMessage.substring(separatorIndex + 1).trim();
      }
      
      loggerStore.addLog({ type, message });
    };

    this.socket.onclose = () => {
      console.log('WebSocket disconnected');
      loggerStore.addLog({ type: 'SYSTEM', message: 'WebSocket 连接已断开。' });
      this.handleReconnect();
    };

    this.socket.onerror = (error) => {
      console.error('WebSocket error:', error);
      loggerStore.addLog({ type: 'FATAL_ERROR', message: 'WebSocket 连接发生错误。' });
    };
  }

  public sendMessage(data: any): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(data));
    } else {
      console.error('WebSocket is not connected.');
      const loggerStore = useLoggerStore();
      loggerStore.addLog({ type: 'FATAL_ERROR', message: '无法发送消息，WebSocket 未连接。' });
    }
  }

  private handleReconnect(): void {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      const delay = Math.pow(2, this.reconnectAttempts) * 1000; // 指数退避
      console.log(`Attempting to reconnect in ${delay / 1000}s...`);
      const loggerStore = useLoggerStore();
      loggerStore.addLog({ type: 'SYSTEM', message: `尝试在 ${delay / 1000} 秒后重新连接... (第 ${this.reconnectAttempts} 次)` });
      setTimeout(() => this.connect(), delay);
    } else {
      console.error('Max reconnect attempts reached.');
      const loggerStore = useLoggerStore();
      loggerStore.addLog({ type: 'FATAL_ERROR', message: '已达到最大重连次数，请刷新页面。' });
    }
  }

  public disconnect(): void {
    if (this.socket) {
      this.socket.close();
    }
  }
}

// 创建一个单例
const wsService = new WebSocketService();

export default wsService;