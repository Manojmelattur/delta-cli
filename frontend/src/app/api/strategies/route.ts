import { NextResponse } from 'next/server';
import { prisma } from '@/lib/db';

export async function GET() {
  try {
    const runs = await prisma.runs.findMany({
      select: { strategy: true },
      distinct: ['strategy'],
      where: { strategy: { not: '' } }
    });
    const strategies = runs.map(r => r.strategy).filter(Boolean);
    return NextResponse.json(strategies);
  } catch (error) {
    console.error("Error fetching strategies:", error);
    return NextResponse.json([], { status: 500 });
  }
}
