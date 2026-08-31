import './globals.css'
import type { Metadata } from 'next'
export const metadata:Metadata={title:'Vasooli — Revenue Recovery Ops',description:'AI revenue recovery batch snapshot'}
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en" className="bg-background"><body>{children}</body></html>}
