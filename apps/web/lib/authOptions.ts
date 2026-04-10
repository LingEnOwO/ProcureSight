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
      from: process.env.EMAIL_FROM,
      async sendVerificationRequest({ identifier: email, url }) {
        const response = await fetch("https://api.sendgrid.com/v3/mail/send", {
          method: "POST",
          headers: {
            Authorization: `Bearer ${process.env.SENDGRID_API_KEY}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            personalizations: [{ to: [{ email }] }],
            from: { email: process.env.EMAIL_FROM },
            subject: "Sign in to ProcureSight",
            content: [
              {
                type: "text/plain",
                value: `Sign in to ProcureSight by clicking this link:\n\n${url}\n\nIf you did not request this, you can ignore this email.`,
              },
              {
                type: "text/html",
                value: `<p>Sign in to ProcureSight by clicking the link below:</p><p><a href="${url}">Sign in</a></p><p>If you did not request this, you can ignore this email.</p>`,
              },
            ],
          }),
        });

        if (!response.ok) {
          const text = await response.text();
          throw new Error(`SendGrid error ${response.status}: ${text}`);
        }
      },
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
      // On sign-in the adapter populates `user`; capture the NextAuth user ID.
      if (user) {
        token.sub = user.id;
      }

      // Always re-fetch business user context from DB so that org_id stays
      // current across DB reseeds or org changes (stale JWTs caused FK errors).
      const email = user?.email ?? token.email;
      if (email) {
        try {
          const result = await publicPool.query(
            `SELECT id, org_id, role, nextauth_user_id
             FROM public.users
             WHERE email = $1`,
            [email]
          );

          if (result.rows.length > 0) {
            const businessUser = result.rows[0];

            // Link NextAuth user to business user on first sign-in
            if (user && !businessUser.nextauth_user_id) {
              await publicPool.query(
                `UPDATE public.users
                 SET nextauth_user_id = $1
                 WHERE id = $2`,
                [user.id, businessUser.id]
              );
            }

            token.businessUserId = businessUser.id;
            token.orgId = businessUser.org_id;
            token.role = businessUser.role;
          } else {
            console.error(`No business user found for email: ${email}`);
            token.businessUserId = null;
            token.orgId = null;
            token.role = null;
          }
        } catch (error) {
          console.error('Error fetching business user context:', error);
          // Keep existing token values on transient DB errors to avoid
          // logging users out during temporary outages.
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