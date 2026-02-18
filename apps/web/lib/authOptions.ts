import type { NextAuthOptions } from "next-auth";
import EmailProvider from "next-auth/providers/email";
import PostgresAdapter from "@auth/pg-adapter";
import { Pool } from "pg";

// Create PostgreSQL connection pool for NextAuth
// Uses same DATABASE_URL as backend for consistency
// Sets search_path to "nextauth" schema to avoid collision with business "users" table
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: 10,
});

// Set search_path for all connections in the pool
pool.on('connect', (client) => {
  client.query('SET search_path TO nextauth, public');
});

// Separate pool for querying public schema (business users)
const publicPool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: 10,
});

export const authOptions: NextAuthOptions = {
  adapter: PostgresAdapter(pool),

  // Required so `next-auth/middleware` can recognize logged-in users
  session: {
    strategy: "jwt",
  },

  // NOTE: Using default NextAuth JWT encoding (JWE - encrypted tokens)
  // Custom encode/decode was removed because it breaks magic link verification
  // Backend doesn't need to decode JWTs - Next.js gateway handles all authentication

  providers: [
    EmailProvider({
      server: process.env.EMAIL_SERVER,
      from: process.env.EMAIL_FROM,
    }),
  ],

  pages: {
    signIn: "/login",
    verifyRequest: "/login?check=1",
  },

  // Configure cookies for cross-port transmission (localhost:3000 → localhost:8000)
  // Removed explicit domain setting - browser will use current host by default
  cookies: {
    sessionToken: {
      name: `next-auth.session-token`,
      options: {
        httpOnly: true,
        sameSite: 'lax' as const,
        path: '/',
        secure: false,  // Must be false for http://localhost
      },
    },
  },

  callbacks: {
    async jwt({ token, user }) {
      // On sign-in (user object exists from adapter)
      if (user) {
        token.sub = user.id;  // NextAuth user ID
        
        try {
          // Query business user by email
          const result = await publicPool.query(
            `SELECT id, org_id, role, nextauth_user_id 
             FROM public.users 
             WHERE email = $1`,
            [user.email]
          );
          
          if (result.rows.length > 0) {
            const businessUser = result.rows[0];
            
            // Link if not already linked
            if (!businessUser.nextauth_user_id) {
              await publicPool.query(
                `UPDATE public.users 
                 SET nextauth_user_id = $1 
                 WHERE id = $2`,
                [user.id, businessUser.id]
              );
            }
            
            // Store business user context in JWT
            token.businessUserId = businessUser.id;
            token.orgId = businessUser.org_id;
            token.role = businessUser.role;
          } else {
            // User authenticated via NextAuth but no business user exists
            console.error(`No business user found for email: ${user.email}`);
            // For now, allow login but mark as incomplete
            token.businessUserId = null;
            token.orgId = null;
            token.role = null;
          }
        } catch (error) {
          console.error('Error linking NextAuth user to business user:', error);
          // Allow login to continue but without business context
          token.businessUserId = null;
          token.orgId = null;
          token.role = null;
        }
      }
      return token;
    },
    
    async session({ session, token }) {
      // Expose user context to client
      if (session.user && token?.sub) {
        (session.user as any).id = token.sub;
        (session.user as any).businessUserId = token.businessUserId;
        (session.user as any).orgId = token.orgId;
        (session.user as any).role = token.role;
      }
      return session;
    },
  },
};