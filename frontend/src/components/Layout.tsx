import { useState, useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import SearchModal from './SearchModal';

export default function Layout() {
  const [showSearch, setShowSearch] = useState(false);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setShowSearch(prev => !prev);
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, []);

  return (
    <div style={{
      width: '100%',
      height: '100%',
      display: 'flex',
      background: 'linear-gradient(180deg, #000 0%, #050509 100%)',
    }}>
      <Sidebar onSearch={() => setShowSearch(true)} />
      <main style={{
        flex: 1,
        overflow: 'auto',
        width: 0,
      }}>
        <Outlet />
      </main>
      {showSearch && <SearchModal onClose={() => setShowSearch(false)} />}
    </div>
  );
}
