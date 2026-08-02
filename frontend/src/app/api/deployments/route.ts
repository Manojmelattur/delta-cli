import { NextResponse } from 'next/server';
import { prisma } from '@/lib/db';

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const id = searchParams.get('id');
    const status = searchParams.get('status');
    const venue = searchParams.get('venue');
    const strategy = searchParams.get('strategy');
    const symbol = searchParams.get('symbol');

    let where: any = {};
    if (id) where.id = parseInt(id);
    if (status) where.status = status;
    if (venue) where.venue = venue;
    if (strategy) where.strategy = strategy;
    if (symbol) where.symbol = symbol;

    const deployments = await prisma.deployments.findMany({
      where,
      orderBy: { id: 'desc' }
    });

    return NextResponse.json({ rows: deployments });
  } catch (error) {
    console.error("Error fetching deployments:", error);
    return NextResponse.json({ rows: [] }, { status: 500 });
  }
}
