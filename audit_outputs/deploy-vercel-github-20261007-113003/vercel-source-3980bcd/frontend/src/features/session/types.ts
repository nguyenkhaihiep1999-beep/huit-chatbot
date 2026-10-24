export type SessionBootstrapErrorCode =
  | 'OFFLINE'
  | 'TIMEOUT'
  | 'CSRF_ERROR'
  | 'SESSION_EXPIRED'
  | 'SERVER_ERROR'
  | 'SESSION_BOOTSTRAP_FAILED';

export class SessionBootstrapError extends Error {
  code: SessionBootstrapErrorCode;
  status?: number;
  requestId?: string;
  userFriendlyMessage: string;

  constructor(params: {
    code: SessionBootstrapErrorCode;
    message?: string;
    status?: number;
    requestId?: string;
    userFriendlyMessage: string;
  }) {
    super(params.message || params.userFriendlyMessage);
    this.name = 'SessionBootstrapError';
    this.code = params.code;
    this.status = params.status;
    this.requestId = params.requestId;
    this.userFriendlyMessage = params.userFriendlyMessage;
  }
}
