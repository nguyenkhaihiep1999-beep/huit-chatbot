/**
 * Public Hook Facade - Chat Feature
 * Re-exports chat hooks and related contracts without business logic or transports.
 */
export {
  useChatStream,
  type UseChatStreamProps,
  type StreamRequestContext,
} from '../src/features/chat/hooks/useChatStream';

export { useConversation } from '../src/features/chat/hooks/useConversation';
