import { BrowserRouter, Route, Routes } from 'react-router'
import './App.css'
import CreateRoom from './pages/CreateRoom.jsx'
import Home from './pages/Home.jsx'
import NotFound from './pages/NotFound.jsx'
import RoomCreated from './pages/RoomCreated.jsx'
import RoomHome from './pages/RoomHome.jsx'
import Settings from './pages/Settings.jsx'

// 정산방 주소는 docs/api-v1.md 초안대로 /rooms/{room_token} (11/6 회의에서 확정)
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/rooms/new" element={<CreateRoom />} />
        <Route path="/rooms/:token" element={<RoomHome />} />
        <Route path="/rooms/:token/created" element={<RoomCreated />} />
        <Route path="/rooms/:token/settings" element={<Settings />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  )
}
