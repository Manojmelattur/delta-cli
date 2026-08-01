import { NextResponse } from 'next/server';
import { prisma } from '@/lib/db';

export async function GET() {
  try {
    const runs = await prisma.runs.findMany({
      select: { symbol: true },
      distinct: ['symbol'],
      where: { symbol: { not: '' } }
    });
    const symbols = runs.map(r => r.symbol).filter(Boolean);
    return NextResponse.json(symbols);
  } catch (error) {
    console.error("Error fetching symbols:", error);
    return NextResponse.json([], { status: 500 });
  }
}
