import { useState } from 'react';
import ProfileModal from './ProfileModal';

export default function UserAvatar({ nickname }: { nickname?: string }) {
  const [showProfile, setShowProfile] = useState(false);
  const initial = (nickname || 'U').charAt(0).toUpperCase();

  return (
    <>
      <div onClick={() => setShowProfile(true)}
        className="flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-white/[0.04] transition-colors cursor-pointer">
        <div className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold"
             style={{ background: 'linear-gradient(135deg, #00F2FF 0%, #BB00FF 100%)', color: '#000' }}>
          {initial}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium truncate" style={{ color: 'var(--text-primary)' }}>{nickname || '用户'}</p>
          <p className="text-[11px] font-mono" style={{ color: 'var(--text-dim)' }}>在线</p>
        </div>
        <div className="w-2 h-2 rounded-full" style={{ background: 'var(--neon-green)' }} />
      </div>
      {showProfile && <ProfileModal onClose={() => setShowProfile(false)} nickname={nickname} />}
    </>
  );
}
